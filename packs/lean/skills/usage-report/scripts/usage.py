#!/usr/bin/env python3
"""Turn Claude Code transcripts into token tables: per project, per day, and the top sessions. Local and read-only.

Reads every .jsonl under ~/.claude/projects (subagent transcripts included, counted under their project). Each
assistant message is counted once, even when Claude Code wrote it over several lines. Columns come from the usage
fields: input, output, cache read (cache_read_input_tokens) and cache write (cache_creation_input_tokens).
The project name is the last part of the working folder recorded in the transcript. Message text is never printed.
No prices: this counts tokens only.

Exit 0 = tables made (and within --limit when given), 1 = total over --limit, 2 = not verified (no usage fields in
the period) or blocked (no transcript folder).
Examples:
  usage.py                         # last 30 days
  usage.py --days 7 --top 5
  usage.py --project-name shop --limit 50000000
"""
import argparse
import datetime
import json
import pathlib
import sys

FIELDS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
HEAD = ("input", "output", "cache read", "cache write", "total")


def read(path, since):
    """Return (project name, session id, {day: [4 sums]}, unread lines) for one transcript."""
    rows, name, bad = {}, None, 0
    with path.open(encoding="utf-8", errors="replace") as fh:
        for n, line in enumerate(fh):
            try:
                rec = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if not isinstance(rec, dict):
                continue
            if name is None and isinstance(rec.get("cwd"), str) and rec["cwd"]:
                name = pathlib.PurePath(rec["cwd"]).name or rec["cwd"]
            msg = rec.get("message") if rec.get("type") == "assistant" else None
            usage = msg.get("usage") if isinstance(msg, dict) else None
            if not isinstance(usage, dict):
                continue
            day = str(rec.get("timestamp", ""))[:10]
            if day < since:
                continue
            row = rows.setdefault(msg.get("id") or rec.get("uuid") or n, {"day": day})
            for field in FIELDS:
                value = usage.get(field)
                if isinstance(value, int) and value >= 0:
                    row[field] = max(row.get(field, 0), value)
    days = {}
    for row in rows.values():
        sums = days.setdefault(row["day"], [0, 0, 0, 0])
        for i, field in enumerate(FIELDS):
            sums[i] += row.get(field, 0)
    session = path.stem if path.parent.name != "subagents" else path.parent.parent.name
    return name, session, days, bad


def add(target, key, sums):
    acc = target.setdefault(key, [0, 0, 0, 0])
    for i, v in enumerate(sums):
        acc[i] += v


def table(title, rows, label, limit=None):
    print(f"\n{title}")
    print(f"  {label:<28}" + "".join(f"{h:>15}" for h in HEAD))
    items = list(rows.items())
    for key, s in items[:limit] if limit else items:
        print(f"  {str(key)[:27]:<28}" + "".join(f"{v:>15,}" for v in (*s, sum(s))))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--projects-dir", type=pathlib.Path, default=pathlib.Path.home() / ".claude" / "projects",
                        help="transcript folder (default: ~/.claude/projects)")
    parser.add_argument("--days", type=int, default=30, help="period in days, today included (default 30)")
    parser.add_argument("--project-name", help="only projects whose folder name is this")
    parser.add_argument("--top", type=int, default=10, help="how many top sessions to list (default 10)")
    parser.add_argument("--limit", type=int, help="total tokens allowed in the period; over it is a fail")
    args = parser.parse_args()
    folder = args.projects_dir.expanduser()
    if not folder.is_dir():
        print(f"RESULT blocked: no transcript folder at {folder}")
        return 2
    if args.days <= 0:
        print("RESULT blocked: --days must be above zero")
        return 2
    start = datetime.date.today() - datetime.timedelta(days=args.days - 1)
    since = start.isoformat()
    cutoff = datetime.datetime.combine(start, datetime.time()).timestamp()

    projects, days, sessions, files, bad = {}, {}, {}, 0, 0
    for path in sorted(folder.rglob("*.jsonl")):
        try:
            if path.stat().st_mtime < cutoff:
                continue
            name, session, by_day, unread = read(path, since)
        except OSError:
            continue
        name = name or path.relative_to(folder).parts[0]
        if args.project_name and name != args.project_name:
            continue
        files += 1
        bad += unread
        for day, sums in by_day.items():
            add(projects, name, sums)
            add(days, day, sums)
            add(sessions, (name, session), sums)

    print(f"usage report: {since} to {datetime.date.today().isoformat()}, {files} transcripts read" +
          (f", {bad} lines not readable" if bad else ""))
    if not projects:
        print("RESULT not verified: no usage fields found in the period")
        return 2
    order = lambda d: dict(sorted(d.items(), key=lambda kv: -sum(kv[1])))
    table("by project", order(projects), "project")
    table("by day", dict(sorted(days.items())), "day")
    top = {f"{p} {s[:8]}": v for (p, s), v in order(sessions).items()}
    table(f"top {min(args.top, len(top))} sessions", top, "project session", args.top)
    total = [sum(v[i] for v in projects.values()) for i in range(4)]
    grand = sum(total)
    read_share = total[2] / (total[0] + total[2] + total[3]) if (total[0] + total[2] + total[3]) else 0
    print(f"\ntotal {grand:,} tokens; cache reads are {read_share:.0%} of input-side tokens")
    if args.limit is not None and grand > args.limit:
        print(f"RESULT fail: {grand:,} tokens in the period, over the limit of {args.limit:,}")
        return 1
    print(f"RESULT pass: {grand:,} tokens over {len(projects)} projects and {len(sessions)} sessions"
          + (f", within the limit of {args.limit:,}" if args.limit is not None else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

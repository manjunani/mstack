#!/usr/bin/env python3
"""Report how big the current Claude Code session is and whether it is time to hand off and start fresh.

Claude Code keeps each session as JSON lines in ~/.claude/projects/<folder-slug>/<session-id>.jsonl, where the slug
is the project path with every character other than a letter or digit replaced by '-'. With no path given, the
newest transcript for the project folder is used.

What it reads (counts only; message text is never printed):
  file size and line count
  assistant turns, each counted once (Claude Code can write one reply over several lines with the same id)
  per turn: input + cache read + cache write tokens = what that call re-read; output tokens
  the latest re-read size, the first, the largest, the average, and compactions seen

Thresholds come from references/thresholds.json (unverified starting points) or --warn-at / --handoff-at.
Exit 0 = below the hand-off line (with a WARNING line in the warning zone), 1 = at or over the hand-off line,
2 = not verified (no usage fields) or blocked (no transcript).
Examples:
  session.py                               # newest session for this folder
  session.py ~/.claude/projects/-home-sam-shop/1234.jsonl
  session.py --project ~/code/shop --handoff-at 120000
"""
import argparse
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent


def limits():
    try:
        data = json.loads((HERE.parent / "references" / "thresholds.json").read_text(encoding="utf-8"))
        return data["warn_context_tokens"]["value"], data["handoff_context_tokens"]["value"]
    except (OSError, ValueError, KeyError):
        return 100000, 150000


def turns(path):
    """Return (turns in order, unread line count, compactions). One entry per assistant message id."""
    by_id, order, bad, compactions = {}, [], 0, 0
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if not isinstance(rec, dict):
                continue
            if rec.get("type") == "system" and rec.get("subtype") == "compact_boundary":
                compactions += 1
            if rec.get("type") != "assistant":
                continue
            msg = rec.get("message") or {}
            usage = msg.get("usage") if isinstance(msg, dict) else None
            if not isinstance(usage, dict):
                continue
            key = msg.get("id") or rec.get("uuid") or len(order)
            if key not in by_id:
                by_id[key] = {}
                order.append(key)
            row = by_id[key]
            for field in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens"):
                value = usage.get(field)
                if isinstance(value, int) and value >= 0:
                    row[field] = max(row.get(field, 0), value)
    return [by_id[k] for k in order], bad, compactions


def reread(row):
    return row.get("input_tokens", 0) + row.get("cache_read_input_tokens", 0) + row.get("cache_creation_input_tokens", 0)


def find_handoff(home):
    claude = home / ".claude"
    for pattern in ("skills/handoff/SKILL.md", "plugins/cache/*/*/*/skills/handoff/SKILL.md"):
        hits = sorted(claude.glob(pattern))
        if hits:
            return hits[0]
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("transcript", nargs="?", type=pathlib.Path, help="a session .jsonl file (default: newest for --project)")
    parser.add_argument("--project", type=pathlib.Path, default=pathlib.Path.cwd(), help="project folder (default: here)")
    parser.add_argument("--home", type=pathlib.Path, default=pathlib.Path.home(), help="home folder (default: yours)")
    parser.add_argument("--projects-dir", type=pathlib.Path, help="transcript folder (default: <home>/.claude/projects)")
    parser.add_argument("--warn-at", type=int, help="re-read tokens per message that start the warning zone")
    parser.add_argument("--handoff-at", type=int, help="re-read tokens per message at which to hand off")
    args = parser.parse_args()

    warn, handoff = limits()
    warn = args.warn_at if args.warn_at is not None else warn
    handoff = args.handoff_at if args.handoff_at is not None else handoff
    home = args.home.expanduser()
    path = args.transcript
    if path is None:
        projects = (args.projects_dir or home / ".claude" / "projects").expanduser()
        slug = re.sub(r"[^A-Za-z0-9]", "-", str(args.project.expanduser().resolve()))
        folder = projects / slug
        files = sorted(folder.glob("*.jsonl"), key=lambda p: p.stat().st_mtime) if folder.is_dir() else []
        if not files:
            print(f"looked for transcripts in {folder}")
            print("RESULT blocked: no session transcript found for this folder; pass the .jsonl path")
            return 2
        path = files[-1]
    path = path.expanduser()
    if not path.is_file():
        print(f"RESULT blocked: no transcript at {path}")
        return 2

    size = path.stat().st_size
    with path.open("rb") as fh:
        lines = sum(1 for _ in fh)
    rows, bad, compactions = turns(path)
    print(f"session {path.stem}")
    print(f"file: {size / 1_000_000:.1f} MB, {lines:,} lines" + (f", {bad} lines not readable" if bad else ""))
    if not rows:
        print("RESULT not verified: the transcript has no usage fields, so the re-read size is unknown; "
              f"the file is {size / 1_000_000:.1f} MB")
        return 2

    sizes = [reread(r) for r in rows]
    latest, first, largest = sizes[-1], sizes[0], max(sizes)
    total_in = sum(sizes)
    cached = sum(r.get("cache_read_input_tokens", 0) for r in rows)
    out = sum(r.get("output_tokens", 0) for r in rows)
    print(f"assistant turns: {len(rows):,}   compactions seen: {compactions}")
    print(f"re-read by each new message now: {latest:,} tokens (first turn {first:,}, largest {largest:,}, "
          f"average {round(total_in / len(rows)):,})")
    print(f"input processed so far: {total_in:,} tokens, {cached / total_in:.0%} of it from cache" if total_in else "input processed so far: 0")
    print(f"output written so far: {out:,} tokens")
    if len(sizes) >= 6:
        recent = sizes[-5:]
        print(f"growth over the last 5 turns: {recent[-1] - recent[0]:+,} tokens")
    print(f"lines: warning at {warn:,}, hand off at {handoff:,} (starting points, not platform limits)")

    skill = find_handoff(home)
    if latest >= handoff:
        if skill:
            print("next: run the handoff skill (found installed), then start a new session from its note")
        else:
            print("next: the handoff skill is not installed; write the goal, what is verified, what is not, and the "
                  "next step into a file, then start a new session that reads it")
        print(f"RESULT fail: each new message re-reads {latest:,} tokens, at or over the hand-off line of {handoff:,}")
        return 1
    if latest >= warn:
        print(f"WARNING each new message re-reads {latest:,} tokens, in the warning zone ({warn:,} to {handoff:,})")
        print(f"RESULT pass: below the hand-off line of {handoff:,}, but in the warning zone; hand off at the next natural break")
        return 0
    print(f"RESULT pass: each new message re-reads {latest:,} tokens, below the warning line of {warn:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

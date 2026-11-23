#!/usr/bin/env python3
"""Keep a token budget for a batch of subagents or eval runs, and check it before each new launch.

Commands:
  estimate  Read past subagent runs (Claude Code writes each one to <session>/subagents/agent-*.jsonl under
            ~/.claude/projects/<folder-slug>/) and print tokens per run: median, 90th percentile and largest. With
            --launches K it prints the cost of K more runs. A run's tokens = input + cache read + cache write +
            output over its assistant messages, each message counted once. --per-run N uses your own figure instead.
  set       Write .mstack/fanout-budget.json in the project: the limit, the per-run figure and the start time.
            This is the only file this skill writes.
  check     Before a launch: measured tokens of runs started since the budget was set, plus runs recorded but not
            yet visible in transcripts, plus --launches x per-run. Over the limit = exit 1 and nothing is recorded.
            With --record and within the limit, the launches are added to the file.

Exit 0 = within budget (or estimate made), 1 = over budget, 2 = not verified or blocked (no past runs and no
--per-run figure, no budget file, bad input).
Examples:
  budget.py estimate --launches 8
  budget.py set --limit 2000000
  budget.py check --launches 2 --record
"""
import argparse
import datetime
import json
import pathlib
import re
import statistics
import sys

FILE = pathlib.Path(".mstack") / "fanout-budget.json"


def run_tokens(path):
    """Return (tokens, first timestamp) for one subagent transcript, or (None, None) if it has no usage fields."""
    rows, first = {}, None
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for n, line in enumerate(fh):
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(rec, dict):
                    continue
                if first is None and isinstance(rec.get("timestamp"), str):
                    first = rec["timestamp"]
                msg = rec.get("message") if rec.get("type") == "assistant" else None
                usage = msg.get("usage") if isinstance(msg, dict) else None
                if not isinstance(usage, dict):
                    continue
                row = rows.setdefault(msg.get("id") or rec.get("uuid") or n, {})
                for field in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens"):
                    value = usage.get(field)
                    if isinstance(value, int) and value >= 0:
                        row[field] = max(row.get(field, 0), value)
    except OSError:
        return None, None
    if not rows:
        return None, first
    return sum(sum(r.values()) for r in rows.values()), first


def parse_time(text):
    try:
        return datetime.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None


def runs(projects_dir, project, all_projects):
    folders = [projects_dir] if all_projects else [projects_dir / re.sub(r"[^A-Za-z0-9]", "-", str(project))]
    found = []
    for folder in folders:
        if folder.is_dir():
            for f in sorted(folder.rglob("subagents/*.jsonl")):
                tokens, first = run_tokens(f)
                if tokens:
                    found.append((tokens, parse_time(first)))
    return found


def describe(values):
    values = sorted(values)
    p90 = values[min(len(values) - 1, int(round(0.9 * (len(values) - 1))))]
    return statistics.median(values), p90, values[-1]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["estimate", "set", "check"])
    parser.add_argument("--project", type=pathlib.Path, default=pathlib.Path.cwd(), help="project folder (default: here)")
    parser.add_argument("--projects-dir", type=pathlib.Path, default=pathlib.Path.home() / ".claude" / "projects",
                        help="transcript folder (default: ~/.claude/projects)")
    parser.add_argument("--all-projects", action="store_true", help="estimate from every project's past runs")
    parser.add_argument("--per-run", type=int, help="tokens per run, when you know it better than past runs")
    parser.add_argument("--launches", type=int, default=1, help="runs about to start (default 1)")
    parser.add_argument("--limit", type=int, help="set: token limit for the whole batch")
    parser.add_argument("--record", action="store_true", help="check: when within the limit, record the launches")
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    projects_dir = args.projects_dir.expanduser()
    if args.launches < 0 or (args.per_run is not None and args.per_run <= 0):
        print("RESULT blocked: --launches cannot be negative and --per-run must be above zero")
        return 2
    path = project / FILE

    if args.command in ("estimate", "set"):
        past = runs(projects_dir, project, args.all_projects)
        if past:
            med, p90, top = describe([t for t, _ in past])
            print(f"past subagent runs: {len(past)}   tokens per run: median {med:,.0f}, 90th percentile {p90:,.0f}, largest {top:,}")
            if len(past) < 5:
                print("WARNING fewer than 5 past runs; the figure is a rough guide")
        else:
            med = p90 = None
            print("past subagent runs: none found" + ("" if args.all_projects else " for this project (try --all-projects)"))
        per_run = args.per_run or (round(p90) if p90 else None)
        source = "given with --per-run" if args.per_run else "90th percentile of past runs"
        if per_run is None:
            print("RESULT blocked: no past runs to learn from; give --per-run with a figure for one run")
            return 2
        if args.command == "estimate":
            print(f"per run used: {per_run:,} ({source})")
            print(f"{args.launches} launches: about {args.launches * per_run:,} tokens"
                  + (f" (median-based: {args.launches * med:,.0f})" if med and not args.per_run else ""))
            print(f"RESULT pass: estimate made for {args.launches} launches; set a limit with: budget.py set --limit <tokens>")
            return 0
        if not args.limit or args.limit <= 0:
            print("RESULT blocked: set needs --limit with a token figure above zero; ask the user for it")
            return 2
        data = {"limit": args.limit, "per_run": per_run, "per_run_source": source,
                "created": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "recorded_launches": 0}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path}")
        print(f"limit {args.limit:,} tokens, {per_run:,} per run ({source}): room for about {args.limit // per_run} runs")
        print(f"RESULT pass: budget set; run 'budget.py check --launches N --record' before each launch")
        return 0

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        limit, per_run, recorded = int(data["limit"]), int(data["per_run"]), int(data.get("recorded_launches", 0))
        created = parse_time(data["created"])
        if created is None:
            raise ValueError("created")
    except (OSError, ValueError, KeyError, TypeError):
        print(f"RESULT blocked: no usable budget file at {path}; run 'budget.py set --limit <tokens>' first")
        return 2
    if args.per_run:
        per_run = args.per_run
    since = [t for t, when in runs(projects_dir, project, args.all_projects) if when and when >= created]
    spent = sum(since)
    waiting = max(0, recorded - len(since))
    projected = spent + waiting * per_run + args.launches * per_run
    print(f"budget: {limit:,} tokens, {per_run:,} per run, set {data['created']}")
    print(f"measured since then: {len(since)} runs, {spent:,} tokens   recorded but not yet seen: {waiting} runs "
          f"(counted at {waiting * per_run:,})")
    print(f"after {args.launches} more: about {projected:,} of {limit:,}")
    if projected > limit:
        room = max(0, (limit - spent - waiting * per_run) // per_run)
        print(f"RESULT fail: {args.launches} more launches would reach about {projected:,} tokens, over the limit of "
              f"{limit:,}; room for {room} more")
        return 1
    if args.record:
        data["recorded_launches"] = recorded + args.launches
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"recorded {args.launches} launches in {path}")
    print(f"RESULT pass: {args.launches} more launches fit; about {limit - projected:,} tokens left after them")
    return 0


if __name__ == "__main__":
    sys.exit(main())

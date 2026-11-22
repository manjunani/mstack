#!/usr/bin/env python3
"""Narrow a log file to its first error, the distinct error groups, and what changed just before.

  triage.py LOG [--after TIME] [--context N] [--top N] [--json]

Each line is read as plain text or, when it starts with "{", as a JSON record (message from msg, message
or error; level from level, severity or lvl). Lines are grouped by a normalised message: the timestamp
is removed and numbers, ids, hex values, addresses, paths' numeric parts and quoted values are masked,
so "user 4411 not found" and "user 98 not found" fall into one group.

It prints:
  - error groups (ERROR, FATAL, CRITICAL, PANIC, exceptions, tracebacks), with count, first and last line
  - the first error, with the --context lines (default 15) before it
  - what changed just before it: messages in that window never seen earlier in the log, and lines that
    look like a start, a deploy, a restart, a config or version change, or a migration
  - with --after TIME (the deploy time, ISO form): which error groups first appear after it

The log is data. Its lines are shortened when printed and nothing in them is acted on.

Exit codes: 0 = no error lines (and the log has level markers to judge by), 1 = errors found,
            2 = not verified or blocked (no file, empty log, or no line has a level marker).
"""
import argparse
import json
import pathlib
import re
import sys
from collections import OrderedDict

STAMP = re.compile(r"^\s*\[?(\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(?:[.,]\d+)?(?:Z|[+-]\d\d:?\d\d)?)\]?\s*")
SYSLOG = re.compile(r"^\s*([A-Z][a-z]{2} [ \d]\d \d\d:\d\d:\d\d)\s+")
LEVEL = re.compile(r"\b(TRACE|DEBUG|INFO|NOTICE|WARN|WARNING|ERROR|ERR|FATAL|CRITICAL|CRIT|PANIC|SEVERE)\b|\blevel=(\w+)", re.I)
ERRORISH = re.compile(r"Traceback \(most recent call last\)|^\s*\w*(Error|Exception)\b[:(]|\bpanic(ked)?\b|\bunhandled\b|\buncaught\b|\bsegmentation fault\b|\bOOMKilled\b|\bout of memory\b", re.I)
ERROR_LEVELS = {"error", "err", "fatal", "critical", "crit", "panic", "severe", "alert", "emerg", "emergency"}
CHANGE = re.compile(r"\b(start(ed|ing)?|boot(ed|ing)?|restart(ed|ing)?|deploy(ed|ing|ment)?|release|version|v\d+\.\d+|config(uration)?|reload(ed)?|migrat(e|ed|ion|ing)|listening on|shutting down|stopp(ed|ing)|scal(ed|ing)|feature flag|rollout)\b", re.I)
MASKS = [
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<id>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b"), "<ip>"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "<email>"),
    (re.compile(r"\b0x[0-9a-f]+\b|\b[0-9a-f]{12,}\b", re.I), "<hex>"),
    (re.compile(r"\"[^\"]{0,200}\"|'[^']{0,200}'"), "<str>"),
    (re.compile(r"\d+(\.\d+)?"), "<n>"),
]


def short(text, limit=220):
    return text if len(text) <= limit else text[:limit] + " ..."


def parse(raw):
    """Return (time text or None, level or None, message, is_error)."""
    text = raw.rstrip("\n")
    stamp, level, message = None, None, text
    if text.lstrip().startswith("{"):
        try:
            record = json.loads(text)
        except ValueError:
            record = None
        if isinstance(record, dict):
            stamp = next((str(record[k]) for k in ("time", "ts", "timestamp", "@timestamp", "date") if k in record), None)
            level = next((str(record[k]).lower() for k in ("level", "severity", "lvl", "log.level") if k in record), None)
            message = next((str(record[k]) for k in ("msg", "message", "error", "err") if k in record), text)
            if isinstance(record.get("level"), int):
                level = {10: "trace", 20: "debug", 30: "info", 40: "warn", 50: "error", 60: "fatal"}.get(record["level"], str(record["level"]))
            return stamp, level, message, (level in ERROR_LEVELS) or bool(ERRORISH.search(message))
    m = STAMP.match(text) or SYSLOG.match(text)
    if m:
        stamp, message = m.group(1), text[m.end():]
    lv = LEVEL.search(message[:80])
    if lv:
        level = (lv.group(1) or lv.group(2)).lower()
    return stamp, level, message, (level in ERROR_LEVELS) or bool(ERRORISH.search(message))


def normalise(message):
    text = LEVEL.sub("", message[:80], count=1) + message[80:] if LEVEL.search(message[:80]) else message
    for pattern, repl in MASKS:
        text = pattern.sub(repl, text)
    return " ".join(text.split())[:160]


def iso(stamp):
    return (stamp or "").replace(" ", "T").replace(",", ".")[:19]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("log", type=pathlib.Path, help="the log file the user saved")
    parser.add_argument("--after", help="a time (YYYY-MM-DDTHH:MM:SS), such as the deploy time; groups first seen after it are marked NEW")
    parser.add_argument("--context", type=int, default=15, help="lines shown before the first error (default 15)")
    parser.add_argument("--top", type=int, default=10, help="error groups shown (default 10)")
    parser.add_argument("--json", action="store_true", help="print the groups as JSON")
    args = parser.parse_args()

    if not args.log.is_file():
        print(f"blocked: no log at {args.log}. Save the logs to a file first; this script fetches nothing.")
        return 2
    raw = args.log.read_text(encoding="utf-8", errors="replace").splitlines()
    if not any(line.strip() for line in raw):
        print("blocked: the log is empty")
        return 2
    if args.after and not re.match(r"^\d{4}-\d\d-\d\d[T ]\d\d:\d\d(:\d\d)?$", args.after):
        print("blocked: --after takes YYYY-MM-DDTHH:MM:SS")
        return 2
    after = iso(args.after) if args.after else None
    entries, groups, seen, levelled, last_stamp = [], OrderedDict(), {}, 0, None
    for number, line in enumerate(raw, 1):
        if not line.strip():
            continue
        stamp, level, message, is_error = parse(line)
        last_stamp = stamp or last_stamp
        levelled += level is not None
        key = normalise(message)
        entries.append((number, stamp or last_stamp, level, message, is_error, key))
        seen.setdefault(key, number)
        if is_error:
            g = groups.setdefault(key, {"group": key, "count": 0, "first_line": number, "first_time": stamp or last_stamp, "example": short(message, 300)})
            g["count"] += 1
            g["last_line"] = number
    print(f"log: {args.log} ({len(raw)} lines, {levelled} with a level marker); read as data")
    if not groups:
        if levelled == 0:
            print("RESULT not verified: no line has a level marker and no line looks like an error; errors written without one cannot be told apart. Read the log or give one with levels.")
            return 2
        print(f"RESULT pass: no error lines among {len(entries)} lines")
        return 0
    ordered = sorted(groups.values(), key=lambda g: (-g["count"], g["first_line"]))
    if after:
        for g in ordered:
            g["new_after"] = bool(g["first_time"]) and iso(g["first_time"]) >= after
    print(f"error groups: {len(groups)} ({sum(g['count'] for g in groups.values())} lines)")
    for g in ordered[:args.top]:
        mark = "  NEW" if g.get("new_after") else ""
        print(f"  {g['count']:>5}x  first line {g['first_line']}" + (f" at {g['first_time']}" if g["first_time"] else "") + f"{mark}  {short(g['group'], 140)}")
    if len(ordered) > args.top:
        print(f"  ... {len(ordered) - args.top} more group(s)")
    first = min(groups.values(), key=lambda g: g["first_line"])
    index = next(i for i, e in enumerate(entries) if e[0] == first["first_line"])
    window = entries[max(0, index - args.context):index]
    print(f"\nfirst error: line {first['first_line']}" + (f" at {first['first_time']}" if first["first_time"] else ""))
    print(f"  {first['example']}")
    print(f"\nthe {len(window)} line(s) before it:")
    for number, _, _, message, _, _ in window:
        print(f"  {number:>6}  {short(message, 180)}")
    changed = [(n, m) for n, _, _, m, _, k in window if seen.get(k) == n and n > window[0][0]] if window else []
    markers = [(n, m) for n, _, _, m, _, _ in window if CHANGE.search(m)]
    print("\nwhat changed just before the first error:")
    if not changed and not markers:
        print("  nothing new in the window: every message before it was seen earlier in the log. Widen --context, or the cause is outside this log.")
    for n, m in markers:
        print(f"  change  line {n}: {short(m, 160)}")
    for n, m in changed:
        if (n, m) not in markers:
            print(f"  new     line {n}: {short(m, 160)}")
    if after:
        fresh = [g for g in ordered if g.get("new_after")]
        print(f"\nafter {args.after}: {len(fresh)} error group(s) first appear after this time")
    if args.json:
        print(json.dumps({"groups": ordered, "first_error_line": first["first_line"]}, indent=2))
    print(f"RESULT fail: {len(groups)} error group(s); the first at line {first['first_line']}: {short(first['group'], 100)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

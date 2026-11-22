#!/usr/bin/env python3
"""Run a seed or factory command more than once and compare what comes out.

Three things can be compared after each run; give at least the first, or one of the others:

  (default)        what the command prints (standard output)
  --state "CMD"    what CMD prints after the command ran, for example a database dump or a row count
  --file PATH      the contents of a file the command writes (repeat for more files)

Examples:
  repeat_check.py -- python3 factories/make_users.py --seed 7        # same seed, same users?
  repeat_check.py --state "python3 scripts/dump_db.py" --no-stdout -- python3 db/seed.py   # safe to seed twice?
  repeat_check.py --ignore "^generated at " -- node seeds/export.js  # leave a timestamp line out, and say so

Each run's compared text is saved under .mstack/test-data/repeat/ so the difference can be read.

Exit codes: 0 = pass: every run gave the same, non-empty result
            1 = fail: the results differ, or the command failed on a later run after passing on the first
            2 = not verified: the command (or the state command) could not run or failed on the first run,
                or there was nothing to compare (empty output, every line ignored)
"""
import argparse
import datetime
import difflib
import hashlib
import pathlib
import re
import shlex
import subprocess
import sys

STATE = pathlib.Path(".mstack") / "test-data" / "repeat"
MASK = "<ignored line>"
TAIL = 12


def run(command, cwd, timeout):
    try:
        done = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout, errors="replace")
    except FileNotFoundError:
        return None, "", f"program not found: {command[0]}"
    except subprocess.TimeoutExpired:
        return None, "", f"timed out after {timeout} seconds"
    return done.returncode, done.stdout, done.stderr


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path.cwd(), help="project folder (default: current folder)")
    parser.add_argument("--runs", type=int, default=2, help="how many times to run the command (default 2)")
    parser.add_argument("--state", metavar="CMD", help="a read-only command whose output describes the data after each run")
    parser.add_argument("--file", action="append", type=pathlib.Path, default=[], help="a file the command writes; compared after each run")
    parser.add_argument("--no-stdout", action="store_true", help="do not compare what the command itself prints")
    parser.add_argument("--ignore", action="append", default=[], metavar="REGEX", help="leave matching lines out of the comparison (they are counted)")
    parser.add_argument("--label", default="check", help="a name for the saved files")
    parser.add_argument("--timeout", type=int, default=600, help="seconds allowed per run (default 600)")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="the seed or factory command, after `--`")
    args = parser.parse_args()
    root = args.root.resolve()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command

    if not command:
        print("blocked: give the command after `--`")
        return 2
    if args.runs < 2:
        print("blocked: --runs has to be at least 2")
        return 2
    if args.no_stdout and not args.state and not args.file:
        print("blocked: --no-stdout leaves nothing to compare; add --state or --file")
        return 2
    try:
        ignores = [re.compile(text) for text in args.ignore]
    except re.error as exc:
        print(f"blocked: --ignore is not a valid regular expression: {exc}")
        return 2

    folder = root / STATE
    folder.mkdir(parents=True, exist_ok=True)
    ignore_file = root / ".mstack" / ".gitignore"
    listed = ignore_file.read_text(encoding="utf-8") if ignore_file.exists() else ""
    if "test-data/repeat/\n" not in listed:
        ignore_file.write_text(listed + "test-data/repeat/\n", encoding="utf-8")
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    label = re.sub(r"[^A-Za-z0-9_-]", "-", args.label)

    snapshots, saved, masked_counts = [], [], []
    for number in range(1, args.runs + 1):
        code, out, err = run(command, root, args.timeout)
        if code != 0:
            what = err.strip().splitlines()[-TAIL:] if code is not None else [err]
            print(f"run {number}: the command failed (exit {code})")
            print("\n".join("  " + line for line in what))
            if number == 1:
                print(f"RESULT not verified: the command does not run cleanly even once (exit {code})")
                return 2
            print(f"RESULT fail: the command passed on run 1 and failed on run {number}: it is not safe to run again")
            return 1
        parts = []
        if not args.no_stdout:
            parts.append(("output", out))
        if args.state:
            scode, sout, serr = run(shlex.split(args.state), root, args.timeout)
            if scode != 0:
                print(f"run {number}: the state command failed (exit {scode}): {serr.strip()[-300:]}")
                print("RESULT not verified: the state after the run could not be read")
                return 2
            parts.append(("state", sout))
        for path in args.file:
            target = path if path.is_absolute() else root / path
            try:
                data = target.read_bytes()
            except OSError as exc:
                print(f"run {number}: cannot read {path}: {exc}")
                print("RESULT not verified: a file to compare was not written")
                return 2
            body = data.decode("utf-8", "replace") if b"\0" not in data[:4096] else f"binary, sha256 {hashlib.sha256(data).hexdigest()}\n"
            parts.append((f"file {path}", body))
        lines, masked = [], 0
        for name, text in parts:
            lines.append(f"## {name}")
            for line in text.splitlines():
                if any(p.search(line) for p in ignores):
                    lines.append(MASK)
                    masked += 1
                else:
                    lines.append(line)
        content = [l for l in lines if not l.startswith("## ") and l != MASK and l.strip()]
        snapshots.append(lines)
        masked_counts.append(masked)
        target = folder / f"{label}-{stamp}-run{number}.txt"
        n = 1
        while target.exists():
            n += 1
            target = folder / f"{label}-{stamp}-{n}-run{number}.txt"
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        saved.append(target)
        print(f"run {number}: exit 0, {len(content)} line(s) to compare" + (f", {masked} ignored" if masked else "") + f"  -> {target}")
        if not content:
            print("RESULT not verified: nothing to compare: the result is empty" + (" once the ignored lines are left out" if masked else ""))
            return 2

    compared = " + ".join(name for name, _ in parts)
    different = [i for i in range(1, len(snapshots)) if snapshots[i] != snapshots[0]]
    if different:
        i = different[0]
        diff = list(difflib.unified_diff(snapshots[0], snapshots[i], f"run 1", f"run {i + 1}", lineterm="", n=0))
        body = [line for line in diff if line[:3] not in ("+++", "---")]
        changed = max(sum(line.startswith("-") for line in body), sum(line.startswith("+") for line in body))
        print(f"\nrun {i + 1} differs from run 1 ({changed} changed line(s)); first differences:")
        print("\n".join("  " + line[:200] for line in diff[2:22]))
        print(f"RESULT fail: {args.runs} runs of the same command gave different results ({compared})")
        return 1
    if any(masked_counts):
        print(f"note: {masked_counts[0]} line(s) per run were left out by --ignore; they were not compared")
    print(f"{args.runs} runs gave the same result ({compared})")
    print("RESULT pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())

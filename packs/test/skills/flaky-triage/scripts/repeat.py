#!/usr/bin/env python3
"""Run a test command many times, record every run, and report how often it fails.

  run      run the command N times; write pass, fail, duration and seed per run to a file
  bisect   find which earlier test makes a victim test fail (order dependence)
  confirm  compare a `before` and an `after` record: is N of N green enough to call it fixed?
  guard    scan the fix (git diff) for retries, skips, removed tests, sleeps and raised timeouts
  summary  list every recorded run in this project

Examples:
  repeat.py run --times 30 --label alone -- python3 -m pytest tests/test_cart.py::test_total
  repeat.py run --times 10 --label shuffled --seed-flag "-p random_order --random-order-seed={seed}" -- python3 -m pytest
  repeat.py bisect --template "python3 -m pytest {tests}" --victim tests/test_b.py --candidates before.txt
  repeat.py confirm --before .mstack/flaky/alone-....jsonl --after .mstack/flaky/after-....jsonl
  repeat.py guard --base main

--seed-flag is the runner's own option for a random order, with {seed} where the number goes. The
script only passes it on; it does not shuffle anything itself. Without it every run uses the plain command.

Exit codes:
  run      0 = every run passed, 1 = at least one run failed, 2 = the command could not be run
  bisect   0 = one polluter found and confirmed, 1 = the search ran but found no single polluter, 2 = preconditions not met
  confirm  0 = fixed with enough runs, 1 = the after record still has failures, 2 = not verified (too few runs, different command, failure never seen)
  guard    0 = no retry, skip or removed test in the diff, 1 = at least one, 2 = no diff to scan
Records are written under .mstack/flaky/ and are never overwritten.
"""
import argparse
import datetime
import json
import math
import pathlib
import random
import re
import shlex
import shutil
import statistics
import subprocess
import sys
import time

STATE = pathlib.Path(".mstack") / "flaky"
KEEP_LOGS = 5

BLOCK = [
    (re.compile(r"\bretr(y|ies|ying)\b|\bretryTimes\b|\breruns?\b|\brerunfailures\b", re.I), "retry"),
    (re.compile(r"@flaky\b|\bflaky\(|\.flaky\b", re.I), "flaky marker"),
    (re.compile(r"@(unittest\.)?skip|\bskipIf\b|\bskipUnless\b|\bxfail\b|\b(it|test|describe)\.skip\b|\bx(it|describe|test)\(|"
                r"@Ignore\b|@Disabled\b|\bt\.Skip\(|#\[ignore\]|\.skip\(|pytest\.skip|\bpending\(", re.I), "skip"),
]
WARN = [
    (re.compile(r"\bsleep\(|\bsetTimeout\(|\bwaitForTimeout\(|Thread\.sleep|\busleep\("), "fixed wait"),
    (re.compile(r"\btimeout\w*\b\s*[:=(,]\s*\d|\bsetDefaultTimeout\(|\bjest\.setTimeout\(", re.I), "timeout value"),
]
TEST_DEF = re.compile(r"^\s*(async\s+)?def\s+test_\w+|^\s*(it|test)\(\s*['\"`]|^\s*func\s+Test\w+\(|^\s*#\[test\]|^\s*@Test\b|^\s*fn\s+test_\w+")
ASSERT = re.compile(r"\bassert\w*\b|\bexpect\(|\bshould\b|\.toBe\w*\(|\.toEqual\(")


def now_stamp():
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def git_out(root, *args):
    try:
        out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout if out.returncode == 0 else None


def new_file(folder, stem, suffix):
    folder.mkdir(parents=True, exist_ok=True)
    ignore = folder.parent / ".gitignore"
    old = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
    if "flaky/\n" not in old:
        ignore.write_text(old + "flaky/\n", encoding="utf-8")
    path, n = folder / f"{stem}{suffix}", 1
    while path.exists():
        n += 1
        path = folder / f"{stem}-{n}{suffix}"
    return path


def strip_dashes(command):
    return command[1:] if command[:1] == ["--"] else command


def run_once(command, cwd, timeout):
    begin = time.time()
    try:
        done = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout, errors="replace")
        return done.returncode, done.stdout + done.stderr, round(time.time() - begin, 3), False
    except subprocess.TimeoutExpired as exc:
        text = (exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return None, text + f"\n[timed out after {timeout} seconds]", round(time.time() - begin, 3), True


def cmd_run(root, args):
    command = strip_dashes(args.command)
    if not command:
        print("blocked: give the test command after `--`")
        return 2
    if args.times < 2:
        print("blocked: --times has to be at least 2; one run says nothing about an intermittent failure")
        return 2
    if args.seed_flag and "{seed}" not in args.seed_flag:
        print("blocked: --seed-flag has to contain {seed} where the runner expects the number")
        return 2
    program = command[0]
    if not (shutil.which(program) or (("/" in program) and (root / program).exists())):
        print(f"blocked: program not found: {program}")
        return 2
    base_seed = args.base_seed if args.base_seed is not None else int(time.time()) % 1000000
    rng = random.Random(base_seed)
    stem = f"{re.sub(r'[^A-Za-z0-9_-]', '-', args.label)}-{now_stamp()}"
    record = new_file(root / STATE, stem, ".jsonl")
    header = {"header": True, "label": args.label, "command": command, "seed_flag": args.seed_flag, "base_seed": base_seed,
              "times": args.times, "timeout": args.timeout, "commit": (git_out(root, "rev-parse", "HEAD") or "").strip() or None,
              "started": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
    rows, saved = [], []
    with record.open("w", encoding="utf-8") as out:
        out.write(json.dumps(header) + "\n")
        for i in range(1, args.times + 1):
            seed = rng.randrange(1, 2**31 - 1) if args.seed_flag else None
            full = command + (shlex.split(args.seed_flag.replace("{seed}", str(seed))) if args.seed_flag else [])
            try:
                code, output, seconds, timed_out = run_once(full, root, args.timeout)
            except FileNotFoundError:
                print(f"blocked: program not found: {command[0]}")
                return 2
            row = {"run": i, "status": "pass" if code == 0 else "fail", "exit_code": code, "seconds": seconds,
                   "seed": seed, "timed_out": timed_out}
            if row["status"] == "fail" and len(saved) < KEEP_LOGS:
                log = record.with_name(f"{record.stem}-run{i}.log")
                log.write_text(output, encoding="utf-8")
                row["output"] = log.name
                saved.append(log)
            out.write(json.dumps(row) + "\n")
            out.flush()
            rows.append(row)
            print(f"  run {i:>3}  {row['status']:4}  exit {code}  {seconds:>8.3f}s" + (f"  seed {seed}" if seed is not None else "")
                  + ("  TIMED OUT" if timed_out else ""), flush=True)
            if args.stop_after_fail and sum(r["status"] == "fail" for r in rows) >= args.stop_after_fail:
                print(f"stopped early after {args.stop_after_fail} failure(s)")
                break
    return report_run(header, rows, record, saved)


def report_run(header, rows, record, saved):
    failed = [r for r in rows if r["status"] == "fail"]
    passed = [r for r in rows if r["status"] == "pass"]
    total = len(rows)
    print(f"\ncommand: {' '.join(header['command'])}" + (f"   + {header['seed_flag']}" if header["seed_flag"] else ""))
    print(f"runs: {total}   passed: {len(passed)}   failed: {len(failed)}   failure rate: {100 * len(failed) / total:.1f}%")
    for name, group in (("passing", passed), ("failing", failed)):
        if group:
            secs = [r["seconds"] for r in group]
            print(f"  {name} runs took  min {min(secs):.3f}s  median {statistics.median(secs):.3f}s  max {max(secs):.3f}s")
    if any(r["timed_out"] for r in failed):
        print(f"  {sum(r['timed_out'] for r in failed)} failing run(s) hit the time limit of {header['timeout']} seconds")
    if header["seed_flag"]:
        print(f"  base seed {header['base_seed']} (pass --base-seed {header['base_seed']} to get the same seeds again)")
        if failed:
            print("  seeds of failing runs: " + ", ".join(str(r["seed"]) for r in failed))
    print(f"record: {record}")
    if saved:
        print(f"output of the first failing run: {saved[0]}")
    if not failed:
        print(f"RESULT pass: {total} of {total} runs passed")
        return 0
    if len(failed) == total:
        print(f"RESULT fail: all {total} runs failed. That is a broken test, not an intermittent one")
        return 1
    print(f"RESULT fail: {len(failed)} of {total} runs failed ({100 * len(failed) / total:.1f}%)")
    return 1


def read_record(path):
    header, rows = None, []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if item.get("header"):
            header = item
        else:
            rows.append(item)
    if header is None or not rows:
        raise ValueError("no header or no runs")
    return header, rows


def cmd_confirm(root, args):
    loaded = []
    for name, path in (("before", args.before), ("after", args.after)):
        try:
            loaded.append(read_record(path))
        except (OSError, ValueError) as exc:
            print(f"RESULT not verified: cannot read the {name} record {path}: {exc}")
            return 2
    (bh, brows), (ah, arows) = loaded
    bfail = sum(r["status"] == "fail" for r in brows)
    afail = sum(r["status"] == "fail" for r in arows)
    print(f"before: {bfail} of {len(brows)} failed   ({' '.join(bh['command'])})")
    print(f"after:  {afail} of {len(arows)} failed   ({' '.join(ah['command'])})")
    if bfail == 0:
        print("RESULT not verified: the before record has no failure, so the problem was never seen")
        return 2
    if afail:
        print(f"RESULT fail: {afail} of {len(arows)} runs still fail after the fix")
        return 1
    if bh["command"] != ah["command"] or bool(bh["seed_flag"]) != bool(ah["seed_flag"]):
        print("RESULT not verified: the after record used a different command or mode than the before record; "
              "run the same command again (a changed command can hide the failure)")
        return 2
    if bfail == len(brows):
        needed = 2
    else:
        rate = bfail / len(brows)
        needed = max(2, math.ceil(math.log(args.risk) / math.log(1 - rate)))
        chance = (1 - rate) ** len(arows)
        print(f"a test that still failed {100 * rate:.1f}% of the time would pass {len(arows)} runs in a row "
              f"{100 * chance:.1f}% of the time (accepted risk: {100 * args.risk:.1f}%)")
    if len(arows) < needed:
        print(f"RESULT not verified: {len(arows)} green runs are too few; run at least {needed}")
        return 2
    print(f"RESULT pass: {len(arows)} of {len(arows)} runs passed with the same command")
    return 0


def cmd_guard(root, args):
    spec = [f"{args.base}...HEAD"] if args.base else ["HEAD"]
    diff = git_out(root, "diff", "--unified=0", "--no-color", *spec, "--", ".", ":(exclude).mstack")
    if diff is None:
        print("RESULT not verified: no git diff available here (not a repository, no commit, or the base does not exist)")
        return 2
    if args.base:
        diff += git_out(root, "diff", "--unified=0", "--no-color", "HEAD", "--", ".", ":(exclude).mstack") or ""
    # new files that git does not track yet are part of the fix too: read them as added lines
    for entry in (git_out(root, "status", "--porcelain=v1", "-uall", "--", ".", ":(exclude).mstack") or "").splitlines():
        if entry.startswith("?? "):
            name = entry[3:].strip().strip('"')
            try:
                body = (root / name).read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            diff += f"+++ b/{name}\n@@ -0,0 +1,{len(body)} @@\n" + "".join(f"+{text}\n" for text in body)
    if not diff.strip():
        print("RESULT not verified: the diff is empty, so there is no fix to scan. If the fix is committed, pass --base <ref>")
        return 2
    blocks, warns, path, line_no = [], [], "?", 0
    removed_tests = added_tests = removed_asserts = added_asserts = 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else line[4:]
        elif line.startswith("@@"):
            match = re.search(r"\+(\d+)", line)
            line_no = int(match.group(1)) - 1 if match else 0
        elif line.startswith("+") and not line.startswith("+++"):
            line_no += 1
            text = line[1:]
            added_tests += bool(TEST_DEF.search(text))
            added_asserts += bool(ASSERT.search(text))
            for pattern, kind in BLOCK:
                if pattern.search(text):
                    blocks.append((kind, path, line_no, text.strip()))
                    break
            else:
                for pattern, kind in WARN:
                    if pattern.search(text):
                        warns.append((kind, path, line_no, text.strip()))
                        break
        elif line.startswith("-") and not line.startswith("---"):
            removed_tests += bool(TEST_DEF.search(line[1:]))
            removed_asserts += bool(ASSERT.search(line[1:]))
    for kind, path, n, text in blocks:
        print(f"  BLOCK {kind:13} {path}:{n}: {text[:120]}")
    if removed_tests > added_tests:
        print(f"  BLOCK removed test   the diff removes {removed_tests} test definition(s) and adds {added_tests}")
    for kind, path, n, text in warns:
        print(f"  warn  {kind:13} {path}:{n}: {text[:120]}")
    if removed_asserts > added_asserts:
        print(f"  warn  fewer assertions: the diff removes {removed_asserts} assertion line(s) and adds {added_asserts}")
    count = len(blocks) + (removed_tests > added_tests)
    print(f"scanned added and removed lines of the diff against {args.base or 'HEAD'}: {count} blocking, "
          f"{len(warns) + (removed_asserts > added_asserts)} to read by hand")
    if count:
        print(f"RESULT fail: the fix adds a retry or skip, or removes a test ({count} place(s) above). That hides the failure; it does not fix it")
        return 1
    print("RESULT pass" + (": read the warn lines; a fixed wait or a larger timeout needs a stated reason" if warns else ""))
    return 0


def probe(template, tests, root, timeout, times, log):
    command = []
    for token in shlex.split(template):
        command.extend(tests if token == "{tests}" else [token])
    result = "pass"
    for _ in range(times):
        code, _, seconds, _ = run_once(command, root, timeout)
        if code != 0:
            result = "fail"
            break
    log.append({"tests": tests, "result": result})
    print(f"  probe {len(log):>2}: {len(tests):>3} test(s) -> {result}", flush=True)
    return result


def cmd_bisect(root, args):
    if "{tests}" not in shlex.split(args.template):
        print("blocked: --template needs {tests} as a separate word, where the test ids go")
        return 2
    candidates = list(args.ids)
    if args.candidates:
        try:
            candidates += [line.strip() for line in args.candidates.read_text(encoding="utf-8").splitlines()
                           if line.strip() and not line.startswith("#")]
        except OSError as exc:
            print(f"blocked: cannot read {args.candidates}: {exc}")
            return 2
    candidates = [c for c in dict.fromkeys(candidates) if c != args.victim]
    if not candidates:
        print("blocked: give the tests that run before the victim, as arguments or with --candidates <file>")
        return 2
    log = []
    try:
        if probe(args.template, [args.victim], root, args.timeout, args.times, log) != "pass":
            print("RESULT not verified: the victim fails when run alone, so test order is not the cause")
            return 2
        if probe(args.template, candidates + [args.victim], root, args.timeout, args.times, log) != "fail":
            print("RESULT not verified: the victim passes after all the candidates, so there is nothing to bisect")
            return 2
        current = candidates
        while len(current) > 1:
            half = len(current) // 2
            first, second = current[:half], current[half:]
            if probe(args.template, first + [args.victim], root, args.timeout, args.times, log) == "fail":
                current = first
            elif probe(args.template, second + [args.victim], root, args.timeout, args.times, log) == "fail":
                current = second
            else:
                print("the victim fails after this set but after neither half of it:")
                print("  " + " ".join(current))
                print("RESULT fail: no single polluter; the failure needs tests from both halves together")
                return 1
        polluter = current[0]
        confirmed = probe(args.template, [polluter, args.victim], root, args.timeout, args.times, log) == "fail"
    except FileNotFoundError:
        print(f"blocked: program not found: {shlex.split(args.template)[0]}")
        return 2
    finally:
        if log:
            path = new_file(root / STATE, f"bisect-{now_stamp()}", ".json")
            path.write_text(json.dumps({"victim": args.victim, "template": args.template, "probes": log}, indent=2) + "\n", encoding="utf-8")
            print(f"record: {path}")
    if not confirmed:
        print(f"RESULT fail: narrowed to {polluter}, but the pair alone passes; the result is not stable")
        return 1
    print(f"polluter: {polluter}")
    print(f"victim:   {args.victim}")
    print(f"RESULT pass: {args.victim} fails only after {polluter} ({len(log)} probes)")
    return 0


def cmd_summary(root, args):
    folder = root / STATE
    files = sorted(folder.glob("*.jsonl")) if folder.is_dir() else []
    if not files:
        print("RESULT not verified: no recorded runs under .mstack/flaky/")
        return 2
    print(f"{'record':40} {'runs':>5} {'failed':>6} {'rate':>7}  command")
    for path in files:
        try:
            header, rows = read_record(path)
        except (OSError, ValueError):
            print(f"{path.name:40} unreadable")
            continue
        failed = sum(r["status"] == "fail" for r in rows)
        mode = " + seed flag" if header.get("seed_flag") else ""
        print(f"{path.name:40} {len(rows):>5} {failed:>6} {100 * failed / len(rows):>6.1f}%  {' '.join(header['command'])}{mode}")
    print("RESULT pass")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path.cwd(), help="project folder (default: current folder)")
    sub = parser.add_subparsers(dest="action", required=True)

    p = sub.add_parser("run", help="run a test command N times and record every run")
    p.add_argument("--times", type=int, default=20, help="number of runs (default 20)")
    p.add_argument("--label", default="run", help="a name for this mode, for example alone, suite, shuffled, after")
    p.add_argument("--seed-flag", help="the runner's random-order option with {seed} in it; a new seed is used for each run")
    p.add_argument("--base-seed", type=int, help="makes the list of seeds repeatable")
    p.add_argument("--timeout", type=int, default=600, help="seconds allowed per run (default 600); a run over the limit counts as a failure")
    p.add_argument("--stop-after-fail", type=int, default=0, help="stop once this many runs have failed (default: run all)")
    p.add_argument("command", nargs=argparse.REMAINDER, help="the test command, after `--`")

    p = sub.add_parser("bisect", help="find the earlier test that makes the victim fail")
    p.add_argument("--template", required=True, help='how to run a list of tests, with {tests} as its own word, e.g. "python3 -m pytest {tests}"')
    p.add_argument("--victim", required=True, help="the test that fails in the suite and passes alone")
    p.add_argument("--candidates", type=pathlib.Path, help="file with one test id per line: the tests that run before the victim")
    p.add_argument("--times", type=int, default=1, help="runs per probe (default 1)")
    p.add_argument("--timeout", type=int, default=600)
    p.add_argument("ids", nargs="*", help="candidate test ids, as an alternative to --candidates")

    p = sub.add_parser("confirm", help="judge an after record against a before record")
    p.add_argument("--before", type=pathlib.Path, required=True, help="record that shows the failure")
    p.add_argument("--after", type=pathlib.Path, required=True, help="record made after the fix, with the same command")
    p.add_argument("--risk", type=float, default=0.05, help="accepted chance that a still-flaky test passes every after run (default 0.05)")

    p = sub.add_parser("guard", help="scan the fix for retries, skips, removed tests, sleeps and timeouts")
    p.add_argument("--base", help="compare with this branch or commit as well as the uncommitted changes (default: uncommitted changes only)")

    sub.add_parser("summary", help="list recorded runs")

    args = parser.parse_args()
    root = args.root.resolve()
    return {"run": cmd_run, "bisect": cmd_bisect, "confirm": cmd_confirm, "guard": cmd_guard, "summary": cmd_summary}[args.action](root, args)


if __name__ == "__main__":
    sys.exit(main())

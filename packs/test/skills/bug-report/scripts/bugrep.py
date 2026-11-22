#!/usr/bin/env python3
"""Reproduce a bug from a clean start, keep the output as evidence, and lint the written report.

  repro  run the reproduction command, save its output, and record reproduced / not reproduced
  lint   check a report: required parts present, evidence files exist, no secrets or personal data

repro needs a marker: text that appears only when the bug happens (--expect "KeyError: 'total'"),
or --expect-exit with the wrong exit code. A non-zero exit alone does not prove this bug: a typo in the
command fails too. --clean runs before each run (a fresh build, an empty test database) and its own
failure stops the run.

The report is a Markdown file with these headings (any level, any order):
  Summary, Steps to reproduce (a numbered list), Expected, Actual, Environment, Evidence
Evidence lists file paths (relative to the report) that have to exist and be non-empty.
Anything the reporter does not know is written as `unknown`, not guessed.

Exit codes:
  repro  0 = reproduced (the marker was seen on every run), 1 = not reproduced on any run,
         2 = not verified: reproduced on some runs only, the clean step failed, or the command could not start
  lint   0 = pass, 1 = fail (problems listed), 2 = not verified (no report file)
Evidence goes to .mstack/bugs/<id>/ and is never overwritten.
"""
import argparse
import datetime
import json
import pathlib
import re
import subprocess
import sys

STATE = pathlib.Path(".mstack") / "bugs"
SECTIONS = {
    "summary": re.compile(r"^#{1,6}\s*summary\b", re.I),
    "steps": re.compile(r"^#{1,6}\s*steps( to reproduce)?\b", re.I),
    "expected": re.compile(r"^#{1,6}\s*expected\b", re.I),
    "actual": re.compile(r"^#{1,6}\s*actual\b", re.I),
    "environment": re.compile(r"^#{1,6}\s*environment\b", re.I),
    "evidence": re.compile(r"^#{1,6}\s*evidence\b", re.I),
}
SECRETS = [
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"), "GitHub token"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "API secret key"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "Slack token"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), "JWT"),
    (re.compile(r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|token|authorization)\b\s*[:=]\s*(?!\s*(unknown|<|\*|redacted|\[))[\"']?[^\s\"']{6,}"), "credential assignment"),
    (re.compile(r"(?i)\bbearer\s+(?!<|\*|redacted)[A-Za-z0-9._~+/-]{16,}"), "bearer token"),
    (re.compile(r"[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@"), "password in a URL"),
]
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")
SAFE_DOMAINS = re.compile(r"(^|\.)(example\.(com|org|net)|test|invalid|localhost)$", re.I)
PHONE = re.compile(r"(?<![\w.])\+\d[\d ()-]{8,18}\d(?!\d)")
CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
TEST_CARDS = {"4242424242424242", "4111111111111111", "5555555555554444", "378282246310005"}


def luhn(digits):
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch) * (2 if i % 2 else 1)
        total += n - 9 if n > 9 else n
    return total % 10 == 0


def new_folder(root, bug_id):
    base = root / STATE
    folder, n = base / bug_id, 1
    while folder.exists():
        n += 1
        folder = base / f"{bug_id}-{n}"
    folder.mkdir(parents=True)
    ignore = root / ".mstack" / ".gitignore"
    listed = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
    if "bugs/\n" not in listed:
        ignore.parent.mkdir(parents=True, exist_ok=True)
        ignore.write_text(listed + "bugs/\n", encoding="utf-8")
    return folder


def shell(command, root, timeout):
    try:
        done = subprocess.run(command, shell=True, cwd=root, capture_output=True, text=True, timeout=timeout, errors="replace")
        return done.returncode, done.stdout + done.stderr
    except subprocess.TimeoutExpired:
        return None, f"[timed out after {timeout} seconds]"


def cmd_repro(root, args):
    if not args.expect and args.expect_exit is None:
        print("blocked: give --expect \"<text only the bug prints>\" or --expect-exit <code>; a failing exit alone proves nothing")
        return 2
    folder = new_folder(root, re.sub(r"[^A-Za-z0-9_-]", "-", args.id))
    record = {"id": args.id, "command": args.command, "clean": args.clean, "expect": args.expect, "expect_exit": args.expect_exit,
              "started": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "runs": []}
    hits = 0
    for n in range(1, args.runs + 1):
        if args.clean:
            code, out = shell(args.clean, root, args.timeout)
            (folder / f"clean-{n}.log").write_text(out, encoding="utf-8")
            if code != 0:
                print(f"run {n}: the clean step failed (exit {code}); see {folder / f'clean-{n}.log'}")
                record["result"] = "not verified: clean step failed"
                (folder / "repro.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
                print("RESULT not verified: the clean start could not be made, so nothing was reproduced from it")
                return 2
        code, out = shell(args.command, root, args.timeout)
        if code == 127 or (code is not None and code != 0 and "not found" in out.lower() and not out.strip().count("\n")):
            (folder / f"run-{n}.log").write_text(out, encoding="utf-8")
            print(f"run {n}: the command could not start: {out.strip()[:200]}")
            print("RESULT not verified: the reproduction command does not run")
            return 2
        seen = (args.expect is None or args.expect in out) and (args.expect_exit is None or code == args.expect_exit)
        hits += seen
        log = folder / f"run-{n}.log"
        log.write_text(f"$ {args.command}\n[exit {code}]\n{out}", encoding="utf-8")
        record["runs"].append({"run": n, "exit_code": code, "marker_seen": seen, "log": log.name})
        print(f"run {n}: exit {code}, marker {'seen' if seen else 'not seen'}  -> {log}")
    record["result"] = "reproduced" if hits == args.runs else ("not reproduced" if hits == 0 else "intermittent")
    (folder / "repro.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"evidence folder: {folder}")
    if hits == args.runs:
        print(f"RESULT pass: reproduced on {hits} of {args.runs} run(s)")
        return 0
    if hits == 0:
        print(f"RESULT fail: not reproduced on any of {args.runs} run(s); the marker never appeared")
        return 1
    print(f"RESULT not verified: reproduced on {hits} of {args.runs} run(s) only: intermittent (flaky-triage can help)")
    return 2


def sections_of(text):
    found, current = {}, None
    for line in text.splitlines():
        hit = next((name for name, pattern in SECTIONS.items() if pattern.match(line.strip())), None)
        if hit:
            current = hit
            found[current] = []
        elif line.strip().startswith("#"):
            current = None
        elif current:
            found[current].append(line)
    return found


def cmd_lint(root, args):
    path = args.report if args.report.is_absolute() else root / args.report
    if not path.is_file():
        print(f"RESULT not verified: report not found: {path}")
        return 2
    text = path.read_text(encoding="utf-8", errors="replace")
    parts = sections_of(text)
    problems = []
    for name in SECTIONS:
        body = "\n".join(parts.get(name, [])).strip()
        if name not in parts:
            problems.append(f"missing section: {name}")
        elif not body:
            problems.append(f"section {name} is empty (write `unknown` if it is not known)")
    steps = [l for l in parts.get("steps", []) if re.match(r"^\s*\d+[.)]\s+\S", l)]
    if "steps" in parts and not steps:
        problems.append("steps to reproduce are not a numbered list")
    expected = " ".join(parts.get("expected", [])).strip().lower()
    actual = " ".join(parts.get("actual", [])).strip().lower()
    if expected and expected == actual:
        problems.append("expected and actual say the same thing")
    evidence = []
    for line in parts.get("evidence", []):
        for item in re.findall(r"`([^`]+)`|\]\(([^)]+)\)|^\s*[-*]\s+(\S+)", line):
            ref = next(x for x in item if x).strip("`<>")
            if not re.match(r"^[a-z]+://", ref):
                evidence.append(ref)
    if "evidence" in parts and not evidence:
        problems.append("evidence names no file")
    for ref in evidence:
        target = pathlib.Path(ref)
        target = target if target.is_absolute() else path.parent / target
        if not target.is_file():
            problems.append(f"evidence file not found: {ref}")
        elif target.stat().st_size == 0:
            problems.append(f"evidence file is empty: {ref}")
    scan = [(str(path.name), text)] + [(ref, (path.parent / ref).read_text(encoding="utf-8", errors="replace"))
                                         for ref in evidence if (path.parent / ref).is_file() and (path.parent / ref).stat().st_size < 2_000_000]
    for name, body in scan:
        for number, line in enumerate(body.splitlines(), 1):
            for pattern, kind in SECRETS:
                if pattern.search(line):
                    problems.append(f"{kind} in {name}:{number}; replace it with <redacted>")
            for match in EMAIL.finditer(line):
                if not SAFE_DOMAINS.search(match.group(1)):
                    problems.append(f"email address in {name}:{number} ({match.group(0)[:1]}***@{match.group(1)}); use user@example.com")
            for match in PHONE.finditer(line):
                problems.append(f"phone number in {name}:{number}; replace it")
            for match in CARD.finditer(line):
                digits = re.sub(r"\D", "", match.group(0))
                if 13 <= len(digits) <= 19 and digits[0] in "23456" and luhn(digits) and digits not in TEST_CARDS:
                    problems.append(f"card number in {name}:{number}; replace it")
    print(f"report: {path}   sections: {', '.join(n for n in SECTIONS if n in parts) or 'none'}   steps: {len(steps)}   evidence files: {len(evidence)}")
    for problem in problems:
        print(f"  problem: {problem}")
    if problems:
        print(f"RESULT fail: {len(problems)} problem(s) above")
        return 1
    print("RESULT pass")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path.cwd(), help="project folder (default: current folder)")
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("repro", help="run the reproduction and save the evidence")
    p.add_argument("--id", required=True, help="a short name for the bug, used for the evidence folder")
    p.add_argument("--command", required=True, help="the reproduction command, as one string")
    p.add_argument("--clean", help="command that makes a clean start before each run")
    p.add_argument("--expect", help="text that appears in the output only when the bug happens")
    p.add_argument("--expect-exit", type=int, help="the wrong exit code the bug produces")
    p.add_argument("--runs", type=int, default=1, help="how many times to run (default 1)")
    p.add_argument("--timeout", type=int, default=600, help="seconds per command (default 600)")
    p = sub.add_parser("lint", help="check a written report")
    p.add_argument("report", type=pathlib.Path, help="the Markdown report")
    args = parser.parse_args()
    root = args.root.resolve()
    return {"repro": cmd_repro, "lint": cmd_lint}[args.action](root, args)


if __name__ == "__main__":
    sys.exit(main())

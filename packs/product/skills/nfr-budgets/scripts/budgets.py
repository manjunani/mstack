#!/usr/bin/env python3
"""Run the check command of each quality budget and report pass or fail against its number.

  template   write an empty budgets file to fill in (refuses if it exists)
  list       print every budget and the command it would run; runs nothing
  baseline   run each check command and record the value it gives now, before any limit is judged
  check      run each check command and compare the value with the budget's number

The budgets file is JSON (default .mstack/budgets.json):
  {"budgets": [{
     "id":        "B-01",
     "quality":   "fast",                      the word this budget replaces
     "metric":    "time to export 10,000 rows",
     "number":    2,                           the limit
     "unit":      "s",
     "direction": "at most",                   or "at least"; default "at most"
     "condition": "on the CI runner, cold cache",
     "check":     "python3 bench/export.py 10000",
     "measure":   "duration"                   how the value is read from the command:
   }]}                                           duration  wall time of the command (unit must be s or ms)
                                                 output    the last number the command prints
                                                 exit      the command's exit code (number is usually 0)

What is refused before anything runs (exit 2):
  - a budget that lacks metric, number, unit, condition or check command, or whose number is not a number
  - check: a budget with no baseline, or whose command changed since its baseline was taken
  - a check command that deletes, resets, pushes, uses sudo or pipes into a shell

How a run is judged:
  pass          the value is within the number
  fail          the value is outside the number
  not verified  the value could not be read: the tool is missing, the command failed, or it printed no number

Exit codes: 0 = every budget passed (baseline: every value was recorded)
            1 = at least one budget failed
            2 = refused, blocked or not verified
The commands in the budgets file are executed, so the user confirms them (see `list`) before the first run.
This script writes only .mstack/budgets-baseline.json and .mstack/budgets-last.json.
"""
import argparse
import datetime
import json
import os
import pathlib
import re
import shlex
import shutil
import statistics
import subprocess
import sys
import time


def _find_git():
    """The git program: MSTACK_GIT when set, otherwise the first git that runs. On macOS /usr/bin/git is
    an xcrun shim that fails inside a sandbox (it cannot write its cache), so the real binaries come next."""
    if os.environ.get("MSTACK_GIT"):
        return os.environ["MSTACK_GIT"]
    for candidate in ("git", "/Applications/Xcode.app/Contents/Developer/usr/bin/git",
                      "/Library/Developer/CommandLineTools/usr/bin/git", "/opt/homebrew/bin/git", "/usr/local/bin/git"):
        try:
            if subprocess.run([candidate, "--version"], capture_output=True, timeout=10).returncode == 0:
                return candidate
        except (OSError, subprocess.SubprocessError):
            continue
    return "git"


GIT = _find_git()

FIVE = ["metric", "number", "unit", "condition", "check"]
MEASURES = ["duration", "output", "exit"]
DIRECTIONS = ["at most", "at least"]
PLACEHOLDER = re.compile(r"\b(tbd|todo|fixme|to be decided|fill in)\b|\?\?\?|<[A-Za-z][^<>]{0,40}>", re.I)
BUILTINS = {"cd", "test", "[", "echo", "export", "set", "time", "if", "for", "while", "!", "(", "{", "exit", "true", "false"}
NUMBER = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
UNSAFE = re.compile(
    r"\brm\s+-|\brmdir\b|\bgit\s+(reset\s+--hard|clean\b|push\b|checkout\s+--)|\bdrop\s+(table|database)\b|\btruncate\s+table\b"
    r"|\bmkfs|\bdd\s+if=|\bsudo\b|\|\s*(sh|bash|zsh)\b|\bshutdown\b|\bkill\s+-9\b|>\s*/dev/", re.I)


def text_ok(value):
    return isinstance(value, str) and value.strip() and not PLACEHOLDER.search(value)


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def load(path):
    if not path.exists():
        print(f"blocked: {path} does not exist. Run: budgets.py template")
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        budgets = data["budgets"]
        if not isinstance(budgets, list):
            raise TypeError("budgets is not a list")
    except (ValueError, KeyError, TypeError) as exc:
        print(f"blocked: {path} must be JSON with a 'budgets' list ({type(exc).__name__})")
        return None
    return budgets


def refusals(budgets, need_number):
    """Return the reasons the file cannot be run as it is."""
    found, seen = [], set()
    if not budgets:
        found.append("the file has no budgets")
    for position, budget in enumerate(budgets, 1):
        if not isinstance(budget, dict):
            found.append(f"budget {position}: not an object")
            continue
        label = budget.get("id") or f"budget {position}"
        if not re.match(r"^B-\d{2,}$", str(budget.get("id", ""))):
            found.append(f"{label}: id must look like B-01")
        if budget.get("id") in seen:
            found.append(f"{label}: id is used twice")
        seen.add(budget.get("id"))
        missing = [f for f in FIVE if f != "number" and not text_ok(budget.get(f))]
        if need_number and not is_number(budget.get("number")):
            missing.append("number")
        if missing:
            found.append(f"{label}: lacks {', '.join(missing)}. A budget needs metric, number, unit, condition and check command")
        elif not need_number and "number" in budget and budget["number"] is not None and not is_number(budget["number"]):
            found.append(f"{label}: number is '{budget['number']}', which is not a number")
        measure = budget.get("measure")
        if measure not in MEASURES:
            found.append(f"{label}: measure must be one of {', '.join(MEASURES)}")
        elif measure == "duration" and str(budget.get("unit", "")).strip() not in ("s", "ms"):
            found.append(f"{label}: a duration is reported in s or ms, not '{budget.get('unit')}'")
        if budget.get("direction", "at most") not in DIRECTIONS:
            found.append(f"{label}: direction must be 'at most' or 'at least'")
        if isinstance(budget.get("check"), str) and UNSAFE.search(budget["check"]):
            found.append(f"{label}: the check command is refused because it can delete, reset, push or run with raised rights: {budget['check']}")
    return found


def measure_once(budget, root, timeout):
    """Run the check command once. Return (value, None) or (None, why it could not be read)."""
    command = budget["check"]
    try:
        program = shlex.split(command)[0]
    except (ValueError, IndexError):
        return None, "the command could not be parsed"
    if "=" not in program and program not in BUILTINS and shutil.which(program) is None and not (root / program).exists():
        return None, f"tool not found: {program}"
    # With pipefail a missing or failing tool early in a pipe is seen, instead of the exit code of the last command.
    bash = shutil.which("bash")
    begin = time.perf_counter()
    try:
        if bash:
            done = subprocess.run([bash, "-o", "pipefail", "-c", command], cwd=root, capture_output=True, text=True, timeout=timeout)
        else:
            done = subprocess.run(command, shell=True, cwd=root, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, f"timed out after {timeout} s"
    elapsed = time.perf_counter() - begin
    if done.returncode == 127:
        return None, "tool not found (exit 127)"
    last = (done.stdout + done.stderr).strip().splitlines()[-1:] or [""]
    if budget["measure"] == "exit":
        return float(done.returncode), None
    if done.returncode != 0:
        return None, f"the command exited {done.returncode}, so its value means nothing: {last[0][:100]}"
    if budget["measure"] == "duration":
        return elapsed * (1000 if budget["unit"].strip() == "ms" else 1), None
    numbers = NUMBER.findall(done.stdout)
    if not numbers:
        return None, "the command printed no number"
    return float(numbers[-1]), None


def measure(budget, root, runs, timeout):
    values = []
    for _ in range(runs):
        value, why = measure_once(budget, root, timeout)
        if why:
            return None, [], why
        values.append(value)
    middle = max(values) if budget["measure"] == "exit" else statistics.median(values)
    return middle, values, None


def commit_of(root):
    try:
        out = subprocess.run([GIT, "-C", str(root), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def fmt(value):
    return f"{value:.3f}".rstrip("0").rstrip(".") if value is not None else "-"


def chosen(budgets, names):
    unknown = set(names) - {b.get("id") for b in budgets}
    if unknown:
        print(f"blocked: no such budget: {', '.join(sorted(unknown))}")
        return None
    return [b for b in budgets if not names or b.get("id") in names]


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except ValueError:
        return {}


def cmd_template(root, args):
    if args.file.exists():
        print(f"blocked: {args.file} already exists; it is not overwritten")
        return 2
    args.file.parent.mkdir(parents=True, exist_ok=True)
    empty = {"id": "B-01", "quality": "", "metric": "", "number": None, "unit": "", "direction": "at most", "condition": "", "check": "", "measure": ""}
    args.file.write_text(json.dumps({"budgets": [empty]}, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.file} with one empty budget. It is refused until metric, unit, condition, check and measure are filled in.")
    print("RESULT pass")
    return 0


def cmd_list(root, args):
    budgets = load(args.file)
    if budgets is None:
        return 2
    for budget in budgets:
        if isinstance(budget, dict):
            limit = f"{budget.get('direction', 'at most')} {budget.get('number')} {budget.get('unit')}" if is_number(budget.get("number")) else "no limit yet"
            print(f"  {budget.get('id')}  {budget.get('metric')} ({limit}; {budget.get('condition')})")
            print(f"        runs: {budget.get('check')}   [reads: {budget.get('measure')}]")
    problems = refusals(budgets, need_number=False)
    for line in problems:
        print("  REFUSED  " + line)
    print("Nothing was run. These commands are executed by baseline and check: show them to the user first.")
    if problems:
        print(f"blocked: {len(problems)} budget problem(s) to fix before anything runs")
        return 2
    print("RESULT pass")
    return 0


def cmd_baseline(root, args):
    budgets = load(args.file)
    if budgets is None:
        return 2
    problems = refusals(budgets, need_number=False)
    if problems:
        for line in problems:
            print("  REFUSED  " + line)
        print(f"blocked: {len(problems)} budget problem(s); nothing was run")
        return 2
    picked = chosen(budgets, args.ids)
    if picked is None:
        return 2
    path = root / ".mstack" / "budgets-baseline.json"
    record = read_json(path)
    unread = []
    for budget in picked:
        print(f"measuring {budget['id']}: {budget['check']}", flush=True)
        value, values, why = measure(budget, root, args.runs, args.timeout)
        if why:
            unread.append(f"{budget['id']} ({why})")
            print(f"  {budget['id']}  not measured: {why}")
            continue
        record[budget["id"]] = {"value": value, "unit": budget["unit"], "runs": values, "command": budget["check"], "measure": budget["measure"],
                                "condition": budget["condition"], "date": datetime.date.today().isoformat(), "commit": commit_of(root)}
        spread = f" (runs: {', '.join(fmt(v) for v in values)})" if len(values) > 1 else ""
        print(f"  {budget['id']}  {budget['metric']}: {fmt(value)} {budget['unit']} now{spread}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"baseline written to {path.relative_to(root)}. Set each number from these values and the user's need, not from memory.")
    if unread:
        print("RESULT not verified: no baseline for " + ", ".join(unread))
        return 2
    print("RESULT pass")
    return 0


def cmd_check(root, args):
    budgets = load(args.file)
    if budgets is None:
        return 2
    problems = refusals(budgets, need_number=True)
    baseline = read_json(root / ".mstack" / "budgets-baseline.json")
    picked = chosen(budgets, args.ids) if not problems else []
    if picked is None:
        return 2
    for budget in picked:
        base = baseline.get(budget["id"])
        if base is None:
            problems.append(f"{budget['id']}: the number was set with no baseline. Run: budgets.py baseline {budget['id']}")
        elif base.get("command") != budget["check"] or base.get("measure") != budget["measure"]:
            problems.append(f"{budget['id']}: the check command changed since the baseline was taken. Run: budgets.py baseline {budget['id']}")
    if problems:
        for line in problems:
            print("  REFUSED  " + line)
        print(f"blocked: {len(problems)} budget problem(s); nothing was run")
        return 2
    results, failed, unread = [], [], []
    for budget in picked:
        print(f"checking {budget['id']}: {budget['check']}", flush=True)
        value, values, why = measure(budget, root, args.runs, args.timeout)
        direction = budget.get("direction", "at most")
        base = baseline[budget["id"]]
        if why:
            verdict = "not verified"
            unread.append(f"{budget['id']} ({why})")
        else:
            within = value <= budget["number"] if direction == "at most" else value >= budget["number"]
            verdict = "pass" if within else "fail"
            if not within:
                failed.append(budget["id"])
        results.append({"id": budget["id"], "metric": budget["metric"], "value": value, "runs": values, "number": budget["number"],
                        "unit": budget["unit"], "direction": direction, "condition": budget["condition"], "baseline": base.get("value"),
                        "verdict": verdict, "why": why})
        print(f"  {budget['id']:6} {verdict:13} {budget['metric']}: {fmt(value)} {budget['unit']} "
              f"(limit: {direction} {fmt(budget['number'])} {budget['unit']}; baseline {fmt(base.get('value'))} on {base.get('date')}; {budget['condition']})"
              + (f"\n         {why}" if why else ""))
    state = root / ".mstack"
    state.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    (state / "budgets-last.json").write_text(json.dumps({"made": stamp, "commit": commit_of(root), "results": results}, indent=2) + "\n", encoding="utf-8")
    ignore = state / ".gitignore"
    lines = ignore.read_text(encoding="utf-8").splitlines() if ignore.exists() else []
    if "budgets-last.json" not in lines:
        ignore.write_text("\n".join(lines + ["budgets-last.json"]) + "\n", encoding="utf-8")
    print(f"{len(results)} budgets run; record in .mstack/budgets-last.json")
    if failed:
        print("RESULT fail: over budget: " + ", ".join(failed))
        return 1
    if unread:
        print("RESULT not verified: " + ", ".join(unread))
        return 2
    print("RESULT pass")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path.cwd(), help="project folder; commands run here (default: current folder)")
    parser.add_argument("--file", type=pathlib.Path, default=None, help="budgets file (default: <root>/.mstack/budgets.json)")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("template", help="write an empty budgets file")
    sub.add_parser("list", help="print the budgets and their commands; runs nothing")
    for name, text in (("baseline", "record the current value of each budget"), ("check", "run each check and compare with its number")):
        p = sub.add_parser(name, help=text)
        p.add_argument("ids", nargs="*", help="budget ids (default: all)")
        p.add_argument("--runs", type=int, default=1, help="times to run each command; the median is used (default 1)")
        p.add_argument("--timeout", type=int, default=600, help="seconds allowed per run (default 600)")
    args = parser.parse_args()
    root = args.root.resolve()
    args.file = (args.file if args.file else root / ".mstack" / "budgets.json").resolve()
    if getattr(args, "runs", 1) < 1:
        print("blocked: --runs must be at least 1")
        return 2
    return {"template": cmd_template, "list": cmd_list, "baseline": cmd_baseline, "check": cmd_check}[args.action](root, args)


if __name__ == "__main__":
    sys.exit(main())

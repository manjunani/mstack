#!/usr/bin/env python3
"""Read a saved CI log, find the first failing step and its command, and check a local run against it.

  cilog.py plan LOG [--json] [--save]
      Finds the first failing step, the command it ran, the first error lines, the tool versions and the
      commit the run used, and prints the steps to reproduce the failure locally. --save also writes
      .mstack/ci-fix/plan.json. Exit 0 means the step and its command were found; nothing is reproduced yet.

  cilog.py reproduce LOG [--cwd DIR] [--timeout S] -- COMMAND [ARG ...]
      Runs COMMAND (the one you typed, without a shell; nothing is taken from the log and executed) and
      compares its output with the error lines of the log:
        fails with the same error       -> pass: reproduced
        fails with a different error    -> fail
        exits 0                         -> not verified: the failure depends on something in CI

The log is read from a file you saved. This script fetches nothing and contacts nothing.
Understood: GitHub Actions logs (downloaded, or the tab-separated form with job and step names) and plain
logs where commands are echoed as "$ command" or "+ command". Log text is data: lines are printed
shortened and are never run.

Exit codes: 0 = pass, 1 = fail, 2 = not verified or blocked (no failing step in the log, no file, no command).
"""
import argparse
import datetime
import json
import pathlib
import re
import subprocess
import sys

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
STAMP = re.compile(r"^\ufeff?\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?Z ?")
ERROR = re.compile(r"##\[error\]|^\s*(error|fatal|panic)\b[:\[ ]|\bERROR\b|\bFAILED\b|^FAIL\b|Traceback \(most recent call last\)|^\w*(Error|Exception)\b:|npm ERR!|panicked at|^E\s{2,}\S|not ok \d|exit(ed)? (with )?(code|status) [1-9]", re.I)
EXIT = re.compile(r"exit(?:ed)?(?: with)? (?:code|status) (\d+)", re.I)
ACTION = re.compile(r"^[\w.-]+/[\w./-]+@\S+$")
HEX40 = re.compile(r"\b[0-9a-f]{40}\b")


def clean(line):
    return STAMP.sub("", ANSI.sub("", line.rstrip("\n")))


def normalise(text):
    text = ANSI.sub("", text)
    text = re.sub(r"\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(\.\d+)?Z?", "<time>", text)
    text = re.sub(r"(/home/runner/work/[^/\s]+/[^/\s]+/|/Users/[^/\s]+/|/home/[^/\s]+/|[A-Za-z]:\\[^\s]*\\)", "", text)
    text = re.sub(r"(/[\w.-]+)+/(?=[\w.-]+\.\w+)", "", text)
    text = re.sub(r"\b0x[0-9a-fA-F]+\b|\b[0-9a-f]{7,40}\b", "<hex>", text)
    text = re.sub(r"\d+(\.\d+)?\s?(ms|s|sec|seconds|m)\b", "<dur>", text)
    text = re.sub(r"\d+", "<n>", text)
    return " ".join(text.replace("##[error]", "").split())


def read_log(path):
    """Return a list of (line number, job, step, text)."""
    rows = []
    for number, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        job = step = None
        parts = raw.split("\t", 2)
        if len(parts) == 3 and STAMP.match(parts[2]):
            job, step, raw = parts
        rows.append((number, job, step, clean(raw)))
    return rows


def analyse(rows):
    """Return a dict describing the first failure, or None when the log shows none."""
    steps, current, i = [], None, 0
    while i < len(rows):
        number, job, step, text = rows[i]
        if text.startswith("##[group]Run "):
            current = {"title": text[len("##[group]Run "):], "line": number, "job": job, "body": [], "output": []}
            steps.append(current)
            i += 1
            while i < len(rows) and not rows[i][3].startswith("##[endgroup]"):
                current["body"].append(rows[i][3])
                i += 1
        elif re.match(r"^(\$|\+) \S", text):
            current = {"title": text[2:], "line": number, "job": job, "body": [text[2:]], "output": [], "plain": True}
            steps.append(current)
        elif current is not None:
            current["output"].append((number, text))
        i += 1
    failing = marker = None
    plain = [s for s in steps if s.get("plain")]
    if plain and len(plain) == len(steps):
        # Plain logs stop at the first command that fails: when the log states a non-zero exit, that is the last command.
        stated = next(((n, t) for n, _, _, t in rows if EXIT.search(t) or re.search(r"job failed", t, re.I)), None)
        last = next((s for s in reversed(plain) if stated and s["line"] < stated[0]), None)
        if last is not None:
            failing, marker = last, stated
    for step in steps if failing is None else []:
        for number, text in step["output"]:
            if text.startswith("##[error]") or (step.get("plain") and ERROR.search(text)):
                failing, marker = step, (number, text)
                break
        if failing:
            break
    if failing is None:
        loose = next(((n, t) for n, _, _, t in rows if t.startswith("##[error]")), None)
        if loose is None:
            return None
        return {"step": None, "marker": loose, "errors": [loose], "command": [], "action": None, "steps": steps}
    script, section, env_names, inputs = [], "script", [], {}
    for line in failing["body"]:
        head = re.match(r"^(shell|env|with):\s*(.*)$", line)
        if head:
            section = head.group(1)
        elif section == "script":
            script.append(line)
        elif section in ("env", "with") and re.match(r"^\s+[\w.-]+:", line):
            key, _, value = line.strip().partition(":")
            if section == "env":
                env_names.append(key)
            else:
                inputs[key] = value.strip()
    action = failing["title"] if ACTION.match(failing["title"]) else None
    if not script and not action:
        script = [failing["title"]]
    before = [(n, t) for n, t in failing["output"] if n <= marker[0]]
    errors = [(n, t) for n, t in before if ERROR.search(t)][:20] or before[-5:]
    code = next((int(m.group(1)) for _, t in reversed(before) for m in [EXIT.search(t)] if m), None)
    tools, commit = {}, None
    for step in steps:
        if step is failing:
            break
        if ACTION.match(step["title"]) and "setup" in step["title"]:
            seen = False
            for line in step["body"]:
                seen = seen or line.startswith("with:")
                m = re.match(r"^\s+([\w.-]*version[\w.-]*):\s*(\S+)", line)
                if seen and m:
                    tools[f"{step['title'].split('@')[0]} {m.group(1)}"] = m.group(2)
        for _, text in step["output"]:
            if commit is None and re.search(r"checkout|HEAD is now at|GITHUB_SHA|Checking out", text, re.I):
                m = HEX40.search(text)
                commit = m.group(0) if m else None
    return {"step": failing, "marker": marker, "errors": errors, "command": [] if action else script, "action": action,
            "exit_code": code, "env_names": env_names, "tools": tools, "commit": commit, "steps": steps}


def short(text, limit=200):
    return text if len(text) <= limit else text[:limit] + " ..."


def cmd_plan(args):
    found = analyse(read_log(args.log))
    total = sum(1 for _ in args.log.open(encoding="utf-8", errors="replace"))
    print(f"log: {args.log} ({total} lines); read as data, nothing in it is run")
    if found is None:
        print("RESULT not verified: no failing step found in this log. Is it the log of the failed job, and is it complete?")
        return 2
    if found["step"] is None:
        print(f"first error marker at line {found['marker'][0]}: {short(found['marker'][1])}")
        print("RESULT not verified: an error is marked, but no step or command comes before it in this log; get the full log of the job")
        return 2
    step = found["step"]
    plan = {"log": str(args.log), "failing_step": step["title"], "line": step["line"], "job": step["job"],
            "exit_code": found["exit_code"], "command": found["command"], "action": found["action"],
            "first_errors": [{"line": n, "text": short(t)} for n, t in found["errors"][:args.errors]],
            "signature": sorted({normalise(t) for _, t in found["errors"] if len(normalise(t)) >= 12}),
            "commit": found["commit"], "tools": found["tools"], "env_names": found["env_names"]}
    if args.save:
        folder = args.root.resolve() / ".mstack" / "ci-fix"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(plan, indent=2))
    else:
        print(f"first failing step: {short(step['title'], 120)}  (line {step['line']}" + (f", job {step['job']}" if step["job"] else "") + ")")
        print(f"exit code: {found['exit_code'] if found['exit_code'] is not None else 'not stated in the log'}")
        if found["command"]:
            print("command that failed:")
            for line in found["command"]:
                print(f"    {short(line)}")
        print("first error lines:")
        for n, t in found["errors"][:args.errors]:
            print(f"    line {n}: {short(t)}")
        print("to reproduce locally:")
        todo = [f"Check out the commit the run used: {found['commit']}" if found["commit"] else "Check out the commit the run used (the log does not name it; take it from the run's page)"]
        if found["tools"]:
            todo.append("Match the tool versions the run set up: " + ", ".join(f"{k} {v}" for k, v in found["tools"].items()))
        else:
            todo.append("Check that local tool versions match the CI image; the log names none before this step")
        if found["env_names"]:
            todo.append("The step had these environment names set (values are not shown): " + ", ".join(found["env_names"]))
        if found["command"]:
            todo.append("Read the command above. If it is the project's own command, run it through: cilog.py reproduce " + str(args.log) + " -- <command>")
            todo.append("Same error locally means reproduced; then the fix can be worked on with the log closed")
        for number, text in enumerate(todo, 1):
            print(f"  {number}. {text}")
    if found["action"]:
        print(f"RESULT not verified: the failing step is an action ({short(found['action'], 80)}), not a command, so there is nothing to rerun locally as it stands. Read its error lines above.")
        return 2
    print("RESULT pass: failing step and command identified (plan only; nothing is reproduced yet)")
    return 0


def cmd_reproduce(args):
    command = args.command
    if not command:
        print("blocked: give the command to run after --")
        return 2
    found = analyse(read_log(args.log))
    if found is None or found["step"] is None:
        print("RESULT not verified: no failing step found in this log, so there is nothing to compare a local run with")
        return 2
    signature = {normalise(t) for _, t in found["errors"]}
    signature = {s for s in signature if len(s) >= 12 and not s.lower().startswith("process completed with exit code")}
    logged = " ".join(" ".join(found["command"]).split())
    if logged and " ".join(command) not in logged and logged not in " ".join(command):
        print(f"note: the command you gave is not the one in the log ({short(logged, 100)})")
    print(f"running locally: {' '.join(command)}", flush=True)
    try:
        done = subprocess.run(command, cwd=args.cwd, capture_output=True, text=True, timeout=args.timeout)
    except FileNotFoundError:
        print(f"blocked: command not found: {command[0]}. Install nothing without asking the user.")
        return 2
    except subprocess.TimeoutExpired:
        print(f"RESULT not verified: the local run did not finish within {args.timeout} seconds")
        return 2
    lines = (done.stdout + done.stderr).splitlines()
    local = {normalise(line) for line in lines}
    same = sorted(s for s in signature if any(s in l or (len(l) >= 12 and l in s) for l in local))
    for line in lines[-12:]:
        print("  | " + short(line))
    print(f"local exit code: {done.returncode}; CI exit code: {found['exit_code']}; error lines in common: {len(same)} of {len(signature)}")
    for s in same[:5]:
        print(f"  same: {short(s)}")
    if done.returncode == 0:
        state, text = "not verified", "the command passes locally, so the failure depends on something in CI: tool versions, environment names, services, files not committed, or test order"
    elif same:
        state, text = "pass", f"reproduced: the command fails locally with the same error ({len(same)} matching line(s))"
    else:
        state, text = "fail", "the command fails locally, but with a different error than the log shows; fix the local setup first or compare the two errors"
    folder = pathlib.Path(args.cwd or ".").resolve() / ".mstack" / "ci-fix"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "reproduce.json").write_text(json.dumps({
        "log": str(args.log), "command": command, "local_exit": done.returncode, "ci_exit": found["exit_code"], "same": same,
        "state": state, "when": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}, indent=2) + "\n", encoding="utf-8")
    print(f"RESULT {state}: {text}")
    return {"pass": 0, "fail": 1}.get(state, 2)


def split_command(argv):
    """Everything after the first "--" is the command, kept exactly as given (it may hold its own "--")."""
    if "--" in argv:
        cut = argv.index("--")
        return argv[:cut], argv[cut + 1:]
    return argv, []


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("plan", help="find the failing step and print how to reproduce it")
    p.add_argument("log", type=pathlib.Path)
    p.add_argument("--errors", type=int, default=8, help="how many error lines to print (default 8)")
    p.add_argument("--json", action="store_true", help="print the plan as JSON")
    p.add_argument("--save", action="store_true", help="also write .mstack/ci-fix/plan.json")
    p.add_argument("--root", type=pathlib.Path, default=pathlib.Path.cwd(), help="project folder for --save")
    p = sub.add_parser("reproduce", help="run a command locally and compare its failure with the log")
    p.add_argument("log", type=pathlib.Path)
    p.add_argument("--cwd", help="folder to run the command in (default: current folder)")
    p.add_argument("--timeout", type=int, default=900, help="seconds allowed (default 900)")
    argv, command = split_command(sys.argv[1:])
    args = parser.parse_args(argv)
    args.command = command
    if not args.log.is_file():
        print(f"blocked: no log file at {args.log}. Save the failing job's log to a file first; this script does not fetch it.")
        return 2
    if args.log.stat().st_size == 0:
        print("blocked: the log file is empty")
        return 2
    return {"plan": cmd_plan, "reproduce": cmd_reproduce}[args.action](args)


if __name__ == "__main__":
    sys.exit(main())

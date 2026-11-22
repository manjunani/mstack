#!/usr/bin/env python3
"""Keep the QA report of one run on disk and check that it is complete.

  init      create the report, with the files the change touched (from git) as its scope
  scenario  add a scenario, or set its final state
  issue     add an issue to a scenario (the scenario becomes `fail`)
  suite     run the project's test suite and record its exit code, or record why it was not run
  check     fail when a scenario has no final state or an issue lacks steps, expected, actual or evidence
  render    write the report as Markdown to a new file

Scenario states: pass, fail, skipped (needs --reason), blocked (needs --reason: what a person must do).
The report is .mstack/qa/report.json unless --report says otherwise. Evidence paths are relative to
the folder of the report (or absolute); each one has to exist and be larger than 0 bytes.

Exit codes of `check`:
  0 = pass: every scenario passed and the test suite is green (or there was nothing to test, with the reason)
  1 = fail: the report is incomplete, or issues were found, or the test suite is red
  2 = not verified: no report, no scenarios, a scenario was skipped or blocked, or the suite was not run
Other commands: 0 = done, 2 = bad input.
"""
import argparse
import datetime
import json
import pathlib
import subprocess
import sys

DEFAULT = pathlib.Path(".mstack") / "qa" / "report.json"
FINAL = ("pass", "fail", "skipped", "blocked")
SEVERITIES = ("high", "medium", "low")
TAIL = 15


def git_lines(root, *args):
    try:
        out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.splitlines() if out.returncode == 0 else None


def load(path):
    if not path.exists():
        return None, f"{path} does not exist; create it with: report.py init --title \"...\""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return None, f"{path} is not valid JSON: {exc}"
    if not isinstance(data, dict):
        return None, f"{path} does not hold a report object"
    data.setdefault("scenarios", [])
    data.setdefault("issues", [])
    return data, None


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def cmd_init(root, path, args):
    if path.exists():
        print(f"blocked: {path} already exists. Continue that run, or pass --report with a new file name.")
        return 2
    scope = {"mode": "whole-app" if args.whole_app else "diff", "base": args.base, "changed_files": [], "note": ""}
    if not args.whole_app:
        committed = git_lines(root, "diff", "--name-only", f"{args.base}...HEAD") if args.base else []
        working = git_lines(root, "status", "--porcelain=v1", "-uall")
        if working is None:
            scope["note"] = "not a git repository: the scope comes from what the user said changed"
        else:
            if committed is None:
                scope["note"] = f"base '{args.base}' not found: only uncommitted changes are listed"
                committed = []
            files = set(committed) | {line[3:].split(" -> ")[-1].strip('"') for line in working if not line[3:].startswith(".mstack/")}
            scope["changed_files"] = sorted(files)
    data = {"title": args.title, "created": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "driver": args.driver or "", "scope": scope, "nothing_to_test": args.nothing_to_test or "",
            "suite": None, "scenarios": [], "issues": []}
    save(path, data)
    print(f"created {path}")
    print(f"scope: {scope['mode']}" + (f", {len(scope['changed_files'])} changed file(s)" if scope["mode"] == "diff" else ""))
    for name in scope["changed_files"][:40]:
        print(f"  {name}")
    if scope["note"]:
        print(f"note: {scope['note']}")
    print("next: add one scenario per user flow these files touch, before opening the app")
    return 0


def cmd_scenario(root, path, args):
    data, err = load(path)
    if err:
        print(f"blocked: {err}")
        return 2
    if args.state in ("skipped", "blocked") and not args.reason:
        print(f"blocked: state '{args.state}' needs --reason")
        return 2
    found = next((s for s in data["scenarios"] if s.get("id") == args.id), None)
    if found is None:
        if not args.name:
            print(f"blocked: scenario {args.id} is new, so it needs --name")
            return 2
        found = {"id": args.id, "flow": "", "name": "", "state": "", "reason": ""}
        data["scenarios"].append(found)
    if args.name:
        found["name"] = args.name
    if args.flow:
        found["flow"] = args.flow
    if args.state:
        if args.state == "pass" and any(i.get("scenario") == args.id for i in data["issues"]):
            print(f"blocked: scenario {args.id} has an issue recorded, so it cannot be set to pass")
            return 2
        found["state"] = args.state
        found["reason"] = args.reason or ""
    save(path, data)
    print(f"scenario {args.id}: {found['state'] or 'no final state yet'}  {found['name']}")
    return 0


def cmd_issue(root, path, args):
    data, err = load(path)
    if err:
        print(f"blocked: {err}")
        return 2
    scenario = next((s for s in data["scenarios"] if s.get("id") == args.scenario), None)
    if scenario is None:
        print(f"blocked: no scenario with id {args.scenario}; add it first")
        return 2
    number = 1 + max([int(i["id"][1:]) for i in data["issues"] if str(i.get("id", ""))[1:].isdigit()] or [0])
    issue = {"id": f"I{number}", "scenario": args.scenario, "title": args.title, "severity": args.severity,
             "steps": args.step or [], "expected": args.expected or "", "actual": args.actual or "",
             "evidence": args.evidence or []}
    data["issues"].append(issue)
    scenario["state"], scenario["reason"] = "fail", ""
    save(path, data)
    print(f"issue {issue['id']} added to {args.scenario}; the scenario is now `fail`")
    for problem in issue_problems(issue, path.parent, {args.scenario: scenario}):
        print(f"  incomplete: {problem}")
    return 0


def cmd_suite(root, path, args):
    data, err = load(path)
    if err:
        print(f"blocked: {err}")
        return 2
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if args.not_run:
        data["suite"] = {"not_run": args.not_run}
        save(path, data)
        print(f"suite: not run ({args.not_run})")
        return 0
    if not command:
        print("blocked: give the suite command after `--`, or --not-run \"<reason>\"")
        return 2
    print(f"running: {' '.join(command)}", flush=True)
    try:
        done = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=args.timeout)
        code, output = done.returncode, done.stdout + done.stderr
    except FileNotFoundError:
        print(f"blocked: program not found: {command[0]}")
        return 2
    except subprocess.TimeoutExpired:
        code, output = None, f"timed out after {args.timeout} seconds"
    data["suite"] = {"command": " ".join(command), "exit_code": code, "tail": output.strip().splitlines()[-TAIL:],
                     "ran": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
    save(path, data)
    print(f"suite: exit {code}")
    return 0


def issue_problems(issue, folder, scenarios):
    out = []
    label = f"issue {issue.get('id', '?')}"
    if not str(issue.get("title", "")).strip():
        out.append(f"{label}: no title")
    scenario = scenarios.get(issue.get("scenario"))
    if scenario is None:
        out.append(f"{label}: points at scenario '{issue.get('scenario')}', which is not in the report")
    elif scenario.get("state") != "fail":
        out.append(f"{label}: its scenario {scenario.get('id')} is '{scenario.get('state')}', not fail")
    steps = [s for s in issue.get("steps") or [] if str(s).strip()]
    if not steps:
        out.append(f"{label}: no steps to reproduce")
    expected, actual = str(issue.get("expected", "")).strip(), str(issue.get("actual", "")).strip()
    if not expected:
        out.append(f"{label}: no expected result")
    if not actual:
        out.append(f"{label}: no actual result")
    if expected and expected.lower() == actual.lower():
        out.append(f"{label}: expected and actual are the same text, so it describes no defect")
    if issue.get("severity") not in SEVERITIES:
        out.append(f"{label}: severity is '{issue.get('severity')}', expected one of {', '.join(SEVERITIES)}")
    evidence = issue.get("evidence") or []
    if not evidence:
        out.append(f"{label}: no evidence file")
    for item in evidence:
        target = pathlib.Path(item)
        target = target if target.is_absolute() else folder / target
        if not target.is_file():
            out.append(f"{label}: evidence file not found: {item}")
        elif target.stat().st_size == 0:
            out.append(f"{label}: evidence file is empty: {item}")
    return out


def problems_in(data, folder):
    out = []
    if not str(data.get("driver", "")).strip():
        out.append("driver is empty: name the browser tool that drove the app")
    scenarios, seen = {}, set()
    for s in data["scenarios"]:
        sid = s.get("id", "?")
        if sid in seen:
            out.append(f"scenario id {sid} is used twice")
        seen.add(sid)
        scenarios[sid] = s
        if not str(s.get("name", "")).strip():
            out.append(f"scenario {sid}: no name")
        state = s.get("state", "")
        if state not in FINAL:
            out.append(f"scenario {sid}: no final state (found '{state}'; allowed: {', '.join(FINAL)})")
        elif state in ("skipped", "blocked") and not str(s.get("reason", "")).strip():
            out.append(f"scenario {sid}: '{state}' without a reason")
        elif state == "fail" and not any(i.get("scenario") == sid for i in data["issues"]):
            out.append(f"scenario {sid}: marked fail but no issue describes what went wrong")
    ids = [i.get("id") for i in data["issues"]]
    for dup in sorted({i for i in ids if ids.count(i) > 1}, key=str):
        out.append(f"issue id {dup} is used twice")
    for issue in data["issues"]:
        out.extend(issue_problems(issue, folder, scenarios))
    suite = data.get("suite")
    if suite is not None and not (isinstance(suite, dict) and ("exit_code" in suite or str(suite.get("not_run", "")).strip())):
        out.append("suite: neither an exit code nor a reason for not running it")
    return out


def cmd_check(root, path, args):
    data, err = load(path)
    if err:
        print(f"RESULT not verified: {err}")
        return 2
    scenarios, issues = data["scenarios"], data["issues"]
    count = {state: sum(1 for s in scenarios if s.get("state") == state) for state in FINAL}
    print(f"report: {path}")
    print(f"scenarios: {len(scenarios)}  " + "  ".join(f"{k} {v}" for k, v in count.items()) + f"   issues: {len(issues)}")
    problems = problems_in(data, path.parent)
    for problem in problems:
        print(f"  incomplete: {problem}")
    if problems:
        print(f"RESULT fail: the report is incomplete ({len(problems)} problem(s) above)")
        return 1
    if not scenarios:
        reason = str(data.get("nothing_to_test", "")).strip()
        if reason:
            print(f"RESULT pass: nothing to test: {reason}")
            return 0
        print("RESULT not verified: the report has no scenarios, and no reason why there is nothing to test")
        return 2
    suite = data.get("suite")
    if count["fail"]:
        print(f"RESULT fail: {len(issues)} issue(s) in {count['fail']} of {len(scenarios)} scenarios")
        return 1
    if suite and "exit_code" in suite and suite["exit_code"] != 0:
        print(f"RESULT fail: the scenarios are green but the test suite is red (exit {suite['exit_code']}: {suite['command']})")
        return 1
    open_items = []
    if count["skipped"]:
        open_items.append(f"{count['skipped']} scenario(s) skipped")
    if count["blocked"]:
        open_items.append(f"{count['blocked']} scenario(s) blocked on a person")
    if suite is None:
        open_items.append("test suite result not recorded")
    elif "exit_code" not in suite:
        open_items.append(f"test suite not run ({suite['not_run']})")
    if open_items:
        print("RESULT not verified: " + "; ".join(open_items))
        return 2
    print("RESULT pass")
    return 0


def cmd_render(root, path, args):
    data, err = load(path)
    if err:
        print(f"blocked: {err}")
        return 2
    out = args.out or path.with_suffix(".md")
    if out.exists() and not args.force:
        print(f"blocked: {out} already exists; pass --force to replace this generated file, or --out for another name")
        return 2
    scope = data.get("scope", {})
    lines = [f"# QA report: {data.get('title', '')}", "",
             f"- Created: {data.get('created', '')}", f"- Browser tool: {data.get('driver', '') or 'not recorded'}",
             f"- Scope: {scope.get('mode', '')}" + (f", {len(scope.get('changed_files', []))} changed files" if scope.get("mode") == "diff" else "")]
    suite = data.get("suite")
    if suite is None:
        lines.append("- Test suite: not recorded")
    elif "exit_code" in suite:
        lines.append(f"- Test suite: `{suite['command']}` exit {suite['exit_code']}")
    else:
        lines.append(f"- Test suite: not run ({suite.get('not_run', '')})")
    lines += ["", "## Scenarios", "", "| Id | Flow | Scenario | State | Reason |", "|---|---|---|---|---|"]
    for s in data["scenarios"]:
        lines.append(f"| {s.get('id', '')} | {s.get('flow', '')} | {s.get('name', '')} | {s.get('state', '') or 'no final state'} | {s.get('reason', '')} |")
    lines += ["", "## Issues", ""]
    if not data["issues"]:
        lines.append("None recorded.")
    for i in data["issues"]:
        lines += [f"### {i.get('id', '')}: {i.get('title', '')}", "",
                  f"- Scenario: {i.get('scenario', '')}", f"- Severity: {i.get('severity', '')}", "", "Steps:", ""]
        lines += [f"{n}. {step}" for n, step in enumerate(i.get("steps") or [], 1)]
        lines += ["", f"Expected: {i.get('expected', '')}", "", f"Actual: {i.get('actual', '')}", "", "Evidence:", ""]
        lines += [f"- {e}" for e in i.get("evidence") or []]
        lines.append("")
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path.cwd(), help="project folder (default: current folder)")
    parser.add_argument("--report", type=pathlib.Path, help=f"report file (default: {DEFAULT})")
    sub = parser.add_subparsers(dest="action", required=True)

    p = sub.add_parser("init", help="create the report and record the scope")
    p.add_argument("--title", required=True, help="what is being tested")
    p.add_argument("--base", default="main", help="branch or commit the change is compared with (default main)")
    p.add_argument("--whole-app", action="store_true", help="scope is the whole app, not the diff")
    p.add_argument("--driver", help="the browser tool that will drive the app")
    p.add_argument("--nothing-to-test", metavar="REASON", help="the change touches no user flow; say why")

    p = sub.add_parser("scenario", help="add a scenario or set its state")
    p.add_argument("id", help="for example S1")
    p.add_argument("--name", help="what the user does and what should be true at the end")
    p.add_argument("--flow", help="the user flow this scenario belongs to")
    p.add_argument("--state", choices=FINAL, help="the final state")
    p.add_argument("--reason", help="needed for skipped and blocked")

    p = sub.add_parser("issue", help="add an issue to a scenario")
    p.add_argument("--scenario", required=True, help="scenario id")
    p.add_argument("--title", required=True)
    p.add_argument("--severity", choices=SEVERITIES, default="medium")
    p.add_argument("--step", action="append", help="one step to reproduce; repeat in order")
    p.add_argument("--expected", help="what should have happened")
    p.add_argument("--actual", help="what happened")
    p.add_argument("--evidence", action="append", help="a screenshot, log or recording saved when the issue was seen; repeat for more")

    p = sub.add_parser("suite", help="run the test suite and record the exit code")
    p.add_argument("--not-run", metavar="REASON", help="record that the suite was not run, and why")
    p.add_argument("--timeout", type=int, default=1800, help="seconds allowed (default 1800)")
    p.add_argument("command", nargs=argparse.REMAINDER, help="the suite command, after `--`")

    sub.add_parser("check", help="check that the report is complete and print the end state")

    p = sub.add_parser("render", help="write the report as Markdown")
    p.add_argument("--out", type=pathlib.Path, help="output file (default: the report path with .md)")
    p.add_argument("--force", action="store_true", help="replace an earlier rendering")

    args = parser.parse_args()
    root = args.root.resolve()
    path = args.report if args.report else root / DEFAULT
    path = path if path.is_absolute() else (root / path)
    handler = {"init": cmd_init, "scenario": cmd_scenario, "issue": cmd_issue, "suite": cmd_suite,
               "check": cmd_check, "render": cmd_render}[args.action]
    return handler(root, path, args)


if __name__ == "__main__":
    sys.exit(main())

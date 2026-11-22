#!/usr/bin/env python3
"""Keep and check the record of one user flow driven on the iPhone simulator.

  start   open a new flow record; needs the name of the tool that will do the tapping
  step    add one step: the action, the screen expected, what was seen, a screenshot, a status
  check   read the whole record again and give one result for the flow

This script does not tap, type or swipe. `xcrun simctl` cannot do that, so the driving is done
by whatever simulator tool the calling agent has. With no such tool, `start --driver none`
ends as blocked and says what is needed.

A step is accepted only with evidence: for `pass` and `fail` a screenshot that exists, is a
readable PNG and is not blank; for `skipped` and `human` a reason. The screenshot is copied
into the record folder as NN.png; the file given is left alone.

`check` fails when a step lacks an action, an expected screen, an observation or a status,
when a screenshot is missing, blank, broken or changed since it was recorded, or when a step
that passed shows exactly the picture of the step before it (an action that changed nothing
proves nothing, unless the step was recorded with --same-screen).

Result of `check`: fail if any step failed or any evidence is bad; not verified if any step
was skipped or left to a person, or the record has no steps; pass otherwise.

Exit codes: 0 = pass (or the step was recorded), 1 = fail (or the step's evidence was refused),
            2 = blocked or not verified (no driver, bad input, steps skipped)
"""
import argparse
import datetime
import hashlib
import json
import pathlib
import re
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import pngstat  # noqa: E402

STATUSES = ("pass", "fail", "skipped", "human")
NO_DRIVER = ("", "none", "no", "n/a", "na", "unknown", "?", "simctl", "xcrun simctl")
NEED_DRIVER = ("a tool that can tap and type on the simulator is needed: the simulator tool of the agent's host, "
               "a UI test target in the project, or a driver the user already has. `xcrun simctl` alone cannot tap. "
               "Nothing was installed. Ask the user which tool to use, or prove single screens with sim-proof.")


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "flow"


def load(folder):
    path = pathlib.Path(folder)
    path = path / "flow.json" if path.is_dir() else path
    if not path.is_file():
        return None, path, f"no flow record at {path}; run `start` first"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return None, path, f"{path} is not valid JSON ({exc})"
    if not isinstance(data, dict) or not isinstance(data.get("steps"), list):
        return None, path, f"{path} has no list of steps"
    return data, path, None


def picture(path, limits):
    """Return (verdict, reason, sha256)."""
    result = pngstat.stats(path, limits)
    verdict, reason = pngstat.judge(result, limits)
    return verdict, reason, result.get("sha256")


def cmd_start(args):
    if args.driver.strip().lower() in NO_DRIVER:
        print(f"blocked: {NEED_DRIVER}")
        return 2
    folder = pathlib.Path(args.dir) if args.dir else pathlib.Path(".mstack") / "sim-flow" / slug(args.name)
    record = folder / "flow.json"
    if record.exists():
        print(f"blocked: {record} already exists. Use another --name or --dir; a record is never overwritten.")
        return 2
    folder.mkdir(parents=True, exist_ok=True)
    data = {"flow": args.name, "driver": args.driver, "app": args.app, "device": args.device,
            "started": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "steps": []}
    record.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"flow record: {record}")
    print(f"driver: {args.driver}")
    print("RESULT pass: record opened with 0 steps; add each step with `step`")
    return 0


def cmd_step(args):
    data, path, error = load(args.dir)
    if error:
        print(f"blocked: {error}")
        return 2
    missing = [n for n in ("action", "expected") if not getattr(args, n).strip()]
    if args.status in ("pass", "fail") and not args.observed.strip():
        missing.append("observed")
    if args.status in ("skipped", "human") and not args.reason.strip():
        missing.append("reason")
    if args.status in ("pass", "fail") and not args.screenshot:
        missing.append("screenshot")
    if missing:
        print(f"blocked: a `{args.status}` step needs --{', --'.join(missing)}")
        return 2
    number = len(data["steps"]) + 1
    entry = {"n": number, "action": args.action.strip(), "expected": args.expected.strip(),
             "observed": args.observed.strip(), "status": args.status, "reason": args.reason.strip(),
             "same_screen": bool(args.same_screen),
             "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
    if args.screenshot:
        try:
            limits, _ = pngstat.load_limits()
        except (OSError, ValueError) as exc:
            print(f"blocked: the thresholds file cannot be used ({exc})")
            return 2
        verdict, reason, digest = picture(args.screenshot, limits)
        if verdict != "real":
            print(f"step {number} not recorded: the screenshot {args.screenshot} is {verdict} ({reason})")
            print(f"RESULT fail: step {number} has no usable evidence; take the screenshot again")
            return 1
        prior = data["steps"][-1] if data["steps"] else None
        if prior and prior.get("sha256") == digest and args.status == "pass" and not args.same_screen:
            print(f"step {number} not recorded: its screenshot is byte for byte the picture of step {prior['n']}.")
            print("RESULT fail: the action changed nothing on screen, or the same file was given twice. "
                  "Take a new screenshot, or record the step with --same-screen if no change is the expected result")
            return 1
        kept = path.parent / f"{number:02d}.png"
        shutil.copyfile(args.screenshot, kept)
        entry["screenshot"], entry["sha256"] = kept.name, digest
    data["steps"].append(entry)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"step {number} recorded as {args.status}: {entry['action']}")
    print(f"RESULT pass: step {number} recorded in {path}")
    return 0


def cmd_check(args):
    data, path, error = load(args.dir)
    if error:
        print(f"blocked: {error}")
        return 2
    driver = str(data.get("driver", "")).strip()
    if driver.lower() in NO_DRIVER:
        print(f"blocked: the record names no driving tool. {NEED_DRIVER}")
        return 2
    try:
        limits, notes = pngstat.load_limits()
    except (OSError, ValueError) as exc:
        print(f"blocked: the thresholds file cannot be used ({exc})")
        return 2
    print(f"flow: {data.get('flow', '?')}   driver: {driver}   record: {path}")
    if notes:
        print("note: image thresholds are mstack defaults, not platform facts: " + "; ".join(notes))
    problems, failed, open_steps, previous = [], [], [], None
    for index, step in enumerate(data["steps"], 1):
        if not isinstance(step, dict):
            problems.append(f"step {index}: not a record")
            continue
        status = step.get("status")
        marks = []
        for field in ("action", "expected"):
            if not str(step.get(field, "")).strip():
                marks.append(f"no {field}")
        if status not in STATUSES:
            marks.append(f"status is '{status}', not one of {', '.join(STATUSES)}")
        digest = None
        if status in ("pass", "fail"):
            if not str(step.get("observed", "")).strip():
                marks.append("no observation")
            shot = step.get("screenshot")
            if not shot:
                marks.append("no screenshot")
            else:
                file = (path.parent / shot) if not pathlib.Path(shot).is_absolute() else pathlib.Path(shot)
                verdict, reason, digest = picture(file, limits)
                if verdict != "real":
                    marks.append(f"screenshot {shot} is {verdict} ({reason})")
                elif step.get("sha256") and step["sha256"] != digest:
                    marks.append(f"screenshot {shot} changed after it was recorded")
                elif status == "pass" and previous and previous == digest and not step.get("same_screen"):
                    marks.append(f"screenshot is identical to step {index - 1}'s")
        elif status in ("skipped", "human") and not str(step.get("reason", "")).strip():
            marks.append("no reason given")
        previous = digest if digest else previous
        if status == "fail":
            failed.append(index)
        if status in ("skipped", "human"):
            open_steps.append(f"{index} ({status}: {step.get('reason', '')})")
        problems += [f"step {index}: {m}" for m in marks]
        print(f"  {index:2}  {str(status):8} {'EVIDENCE BAD' if marks else 'evidence ok':13} {str(step.get('action', ''))[:60]}")
        if status == "fail":
            print(f"        expected: {step.get('expected', '')}\n        observed: {step.get('observed', '')}")
    total = len(data["steps"])
    print(f"checked: {total} steps; {len(failed)} failed, {len(open_steps)} skipped or left to a person, {len(problems)} evidence problems")
    for line in problems:
        print(f"  problem: {line}")
    if problems:
        print(f"RESULT fail: {len(problems)} evidence problems; first: {problems[0]}")
        return 1
    if failed:
        print(f"RESULT fail: step {', '.join(map(str, failed))} failed")
        return 1
    if total == 0:
        print("RESULT not verified: the record has no steps")
        return 2
    if open_steps:
        print(f"RESULT not verified: steps not driven: {'; '.join(open_steps)}")
        return 2
    print(f"RESULT pass: {total} of {total} steps passed with a screenshot each")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start", help="open a new flow record")
    start.add_argument("--name", required=True, help="the flow, in a few words: \"sign in\"")
    start.add_argument("--driver", required=True, help="name of the tool that taps on the simulator; `none` when there is none")
    start.add_argument("--app", default="", help="bundle id of the app")
    start.add_argument("--device", default="", help="simulator name or id")
    start.add_argument("--dir", help="folder for the record (default .mstack/sim-flow/<name>)")
    step = sub.add_parser("step", help="add one step with its evidence")
    step.add_argument("--dir", required=True, help="the record folder printed by `start`")
    step.add_argument("--action", required=True, help="what was done: \"tap Sign in\"")
    step.add_argument("--expected", required=True, help="the screen or state expected after the action")
    step.add_argument("--observed", default="", help="what the screen really showed")
    step.add_argument("--screenshot", help="PNG taken after the action")
    step.add_argument("--status", required=True, choices=STATUSES)
    step.add_argument("--reason", default="", help="why the step was skipped or left to a person")
    step.add_argument("--same-screen", action="store_true", help="the expected result is that the screen does not change")
    check = sub.add_parser("check", help="check the whole record")
    check.add_argument("dir", help="the record folder, or the path of flow.json")
    args = parser.parse_args()
    return {"start": cmd_start, "step": cmd_step, "check": cmd_check}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())

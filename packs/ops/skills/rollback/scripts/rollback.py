#!/usr/bin/env python3
"""Check a rollback plan, run its command only on an explicit flag, and confirm the old version is serving.

  rollback.py plan --previous ID --command "CMD" --data compatible|incompatible|unknown [--data-reason TEXT]
                   --check-url URL [--expect TEXT] [--current ID] [--max-ms N]
      Writes .mstack/rollback/plan.json and checks it has all four parts:
        previous   the version to return to (a commit, tag, image or deployment id)
        command    the command that returns to it, written out in full
        data       is the old code compatible with the data as it is now? (migrations applied since the
                   bad deploy may have changed it). "compatible" needs a reason; "incompatible" and
                   "unknown" stop the plan: a rollback onto changed data can break more than it fixes.
        check      an address to request afterwards, and the text that proves the old version answers
                   (default: the previous id)
      The plan passes, or ends blocked with the parts that are missing. It runs nothing.

  rollback.py apply --execute
      Runs the planned command (without a shell) and records its exit code and last lines. Without
      --execute it prints the command and runs nothing. Use --execute only after the user said yes to
      this exact command.

  rollback.py confirm [--repeat N]
      Requests the check address (logic copied from deploy-check's probe.py) and passes only when the
      previous version answers on every request.

Exit codes: 0 = pass, 1 = fail (the command failed, or the old version is not serving),
            2 = not verified or blocked (plan incomplete, data not compatible, no yes, nothing planned).
"""
import argparse
import datetime
import json
import pathlib
import shlex
import subprocess
import sys

import probe

STATE = pathlib.Path(".mstack") / "rollback"


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def plan_path(root):
    return root / STATE / "plan.json"


def save(root, plan):
    path = plan_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    return path


def cmd_plan(args, root):
    plan = {"previous": (args.previous or "").strip(), "current": (args.current or "").strip(), "command": (args.command or "").strip(),
            "data": args.data, "data_reason": (args.data_reason or "").strip(), "check_url": (args.check_url or "").strip(),
            "expect": (args.expect or args.previous or "").strip(), "max_ms": args.max_ms, "made": now(), "applied": None, "confirmed": None}
    missing, stops, notes = [], [], []
    if not plan["previous"]:
        missing.append("previous: which version to return to (a commit, tag, image or deployment id)")
    elif plan["current"] and plan["previous"] == plan["current"]:
        stops.append(f"previous and current are both '{plan['previous']}': rolling back to the version that is running changes nothing")
    if not plan["command"]:
        missing.append("command: the exact command that returns to the previous version")
    else:
        try:
            words = shlex.split(plan["command"])
        except ValueError as exc:
            words = []
            stops.append(f"the command does not parse: {exc}")
        if words and plan["previous"] and not any(plan["previous"] in w for w in words):
            notes.append(f"the command does not name '{plan['previous']}'; make sure it does not return to some other version, such as 'the one before whatever is live'")
        if any(c in plan["command"] for c in ("|", ";", "&&", "`", "$(")):
            stops.append("the command chains or pipes several commands; write one command, so that exactly that is what the user says yes to")
    if plan["data"] is None:
        missing.append("data: is the old code compatible with the data as it is now (--data compatible|incompatible|unknown)")
    elif plan["data"] == "incompatible":
        stops.append("the data is not compatible with the old code. Rolling back would put old code on changed data. The user decides: fix forward, or reverse the data change first (with its own check and backup).")
    elif plan["data"] == "unknown":
        stops.append("nobody knows whether the old code works with the current data. Find out first: list the migrations applied since the previous version (migration-check can read them).")
    elif not plan["data_reason"]:
        missing.append("data reason: why the old code is compatible (for example: no migration since the previous version)")
    if not plan["check_url"]:
        missing.append("check: the address to request after the rollback (--check-url)")
    else:
        problem = probe.valid_url(plan["check_url"])
        if problem:
            missing.append(f"check: {problem}")
    if not plan["expect"]:
        missing.append("check: the text that proves the previous version answers (--expect)")
    path = save(root, plan)
    for label, value in (("previous", plan["previous"]), ("command", plan["command"]),
                         ("data", f"{plan['data']}: {plan['data_reason']}" if plan["data"] else ""),
                         ("check", f"{plan['check_url']} expecting '{plan['expect']}'" if plan["check_url"] else "")):
        print(f"  {label:9} {value or '(missing)'}")
    for line in notes:
        print(f"  note: {line}")
    print(f"plan: {path}")
    if stops or missing:
        print("blocked: " + "; ".join(stops + missing))
        return 2
    print("RESULT pass: the plan is complete. Nothing was run. Show the command to the user and wait for a yes before apply --execute.")
    return 0


def load_plan(root):
    path = plan_path(root)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def complete(plan):
    return bool(plan["previous"] and plan["command"] and plan["data"] == "compatible" and plan["data_reason"] and plan["check_url"] and plan["expect"])


def cmd_apply(args, root):
    plan = load_plan(root)
    if plan is None or not complete(plan):
        print("blocked: no complete plan; run plan first and fix what it lists")
        return 2
    words = shlex.split(plan["command"])
    if not args.execute:
        print(f"would run: {plan['command']}")
        print("blocked: not run. This changes a live service: show the command to the user, and after a yes run apply --execute")
        return 2
    print(f"running: {plan['command']}", flush=True)
    try:
        done = subprocess.run(words, cwd=root, capture_output=True, text=True, timeout=args.timeout)
        code, tail = done.returncode, (done.stdout + done.stderr).strip().splitlines()[-15:]
    except FileNotFoundError:
        print(f"blocked: command not found: {words[0]}")
        return 2
    except subprocess.TimeoutExpired:
        code, tail = None, [f"timed out after {args.timeout} seconds; the service may be part way through the change"]
    for line in tail:
        print("  | " + line)
    plan["applied"] = {"exit": code, "tail": tail, "when": now()}
    save(root, plan)
    if code != 0:
        print(f"RESULT fail: the rollback command exited {code}. Check the service's state before trying anything else.")
        return 1
    print("RESULT pass: the command exited 0. That is not proof the old version serves; run confirm.")
    return 0


def cmd_confirm(args, root):
    plan = load_plan(root)
    if plan is None or not complete(plan):
        print("blocked: no complete plan; run plan first")
        return 2
    print(f"checking {plan['check_url']} for '{plan['expect']}' ({args.repeat} requests, GET)")
    state, reason, record = probe.probe(plan["check_url"], plan["expect"], max_ms=plan.get("max_ms"), repeat=args.repeat,
                                        interval=args.interval, timeout=args.timeout)
    for line in record["problems"]:
        print("  FAIL " + line)
    plan["confirmed"] = {"state": state, "reason": reason, "when": now()}
    save(root, plan)
    if plan["applied"] is None:
        print("  note: apply was not run through this script; if the rollback was made another way, say how")
    if state == "pass":
        print(f"RESULT pass: the previous version '{plan['expect']}' is serving; {reason}")
        return 0
    print(f"RESULT {state}: {reason}")
    return 1 if state == "fail" else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path.cwd(), help="project folder for .mstack/rollback (default: current folder)")
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("plan", help="write and check the rollback plan")
    p.add_argument("--previous", help="the version to return to")
    p.add_argument("--current", help="the version running now (optional, to catch a no-op)")
    p.add_argument("--command", help="the full command that returns to the previous version")
    p.add_argument("--data", choices=["compatible", "incompatible", "unknown"], help="is the old code compatible with the current data")
    p.add_argument("--data-reason", help="why (required for compatible)")
    p.add_argument("--check-url", help="address to request after the rollback")
    p.add_argument("--expect", help="text that proves the previous version answers (default: --previous)")
    p.add_argument("--max-ms", type=float, help="limit for the median response time")
    p = sub.add_parser("apply", help="run the planned command (only with --execute)")
    p.add_argument("--execute", action="store_true", help="really run it; only after the user said yes to this command")
    p.add_argument("--timeout", type=int, default=900)
    p = sub.add_parser("confirm", help="check that the previous version is serving")
    p.add_argument("--repeat", type=int, default=3)
    p.add_argument("--interval", type=float, default=1.0)
    p.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    root = args.root.resolve()
    return {"plan": cmd_plan, "apply": cmd_apply, "confirm": cmd_confirm}[args.action](args, root)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""mstack-lean PreToolUse hook on the Agent and Task tools: keeps subagent launches inside a budget.

With a budget set by the fanout-budget skill (.mstack/fanout-budget.json in the project), each launch
counts one run at the budget's per-run estimate. When the next launch would go over the limit, the
hook answers "ask" with the numbers, so the user decides. Allowed launches are recorded in the same
file. With no budget set it allows silently, and adds one warning line once the session has already
launched many agents (default 10, from limits.json).

Off switch: MSTACK_LEAN=off. Any error allows the launch.
"""
import json
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
LAUNCH_TOOLS = {"Agent", "Task"}


def answer(decision=None, reason=None, note=None):
    out = {}
    if decision:
        out["hookSpecificOutput"] = {"hookEventName": "PreToolUse", "permissionDecision": decision,
                                     "permissionDecisionReason": "mstack-lean: " + reason}
    if note:
        out["systemMessage"] = "mstack-lean: " + note
    if out:
        print(json.dumps(out))
    sys.exit(0)


def find_budget(cwd):
    for folder in (cwd, *cwd.parents):
        path = folder / ".mstack" / "fanout-budget.json"
        if path.exists():
            return path
    return None


def launches_so_far(transcript):
    count = 0
    if not transcript or not os.path.exists(transcript):
        return 0
    with open(transcript, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if '"tool_use"' in line and ('"name":"Agent"' in line or '"name":"Task"' in line
                                         or '"name": "Agent"' in line or '"name": "Task"' in line):
                count += 1
    return count


def main():
    if os.environ.get("MSTACK_LEAN", "").lower() == "off":
        return
    event = json.load(sys.stdin)
    if event.get("tool_name") not in LAUNCH_TOOLS:
        return
    cwd = pathlib.Path(event.get("cwd") or os.getcwd()).resolve()
    path = find_budget(cwd)
    if path is None:
        warn_at = int(json.loads((HERE / "limits.json").read_text(encoding="utf-8"))["agents_warning_count"])
        done = launches_so_far(event.get("transcript_path"))
        if done + 1 == warn_at:
            answer(note=f"this session is starting its {warn_at}th agent and no budget is set. "
                        "Each agent can cost millions of tokens; the fanout-budget skill sets a limit.")
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    limit, per_run = int(data["limit"]), int(data["per_run"])
    recorded = int(data.get("recorded_launches", 0))
    projected = (recorded + 1) * per_run
    if projected > limit:
        answer("ask", f"this launch would bring the estimate to about {projected:,} tokens, over the budget of "
                      f"{limit:,} ({recorded} launches recorded at {per_run:,} each). Allow it, or raise the budget "
                      f"with the fanout-budget skill.")
    data["recorded_launches"] = recorded + 1
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:  # fail open: a broken hook must never block work
        pass
    sys.exit(0)

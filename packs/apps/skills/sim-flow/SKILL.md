---
name: sim-flow
description: Records a user flow on the iPhone simulator step by step and checks the record: each step has an action, the screen expected, what was seen and a non-blank screenshot, with one result for the whole flow. Use when the user asks to walk through sign-up, checkout or onboarding on the simulator, "tap through the app and check each screen" or "test this flow on iPhone". Not for proving one launch screen (use sim-proof) or for web flows in a browser (use qa-run).
license: MIT
metadata:
  pack: apps
  version: 0.1.0
  needs: python3, a tool that can tap on the simulator (the host agent's simulator tool or the project's UI tests)
---

# Sim flow

Produces `.mstack/sim-flow/<flow>/flow.json` with one checked step per action and a screenshot for each, and one result for the flow.

## Done when

- `scripts/flowcheck.py check <record>` exits 0: every step passed with its own screenshot.
- Steps a simulator cannot do (purchases, Sign in with Apple, push, a real camera) are recorded as `human` with the exact action and expected result for the user.

End in exactly one state: **pass**, **fail** (the failing step with expected and observed), **not verified** (steps skipped or left to a person), or **blocked** (no tool that can tap).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| A tapping tool | the host's own simulator tool is listed among your tools, or the project has a UI test target | plain `xcrun simctl` cannot tap. Say so, ask which tool to use, end as blocked. Do not install one |
| The app running | run `sim-proof` first if installed; otherwise launch it with the tapping tool | blocked |

## Steps

The script is `scripts/flowcheck.py` in this skill's folder (`"${CLAUDE_SKILL_DIR}/scripts/flowcheck.py"` in Claude Code).

1. **Name the steps** with the user: action and expected screen for each, in order.
2. **Open the record**, naming the real tool that will tap:
   ```
   python3 scripts/flowcheck.py start --name "sign in" --driver "<tool name>" --app <bundle id>
   ```
   With no tool, `--driver none` prints the blocked message; report it.
3. **For each step:** read the screen's element tree first if the tool offers it, act by label or id (not by coordinates when avoidable), wait for the expected element, take a screenshot, then record:
   ```
   python3 scripts/flowcheck.py step --dir <record> --action "tap Sign in" --expected "form with email field" --observed "<what you saw>" --screenshot <png> --status pass
   ```
   A tap that returned success proves nothing; the observation and the screenshot decide. A step the script refuses (blank or repeated picture) is taken again, not forced.
4. **Check.** `python3 scripts/flowcheck.py check <record>`.
5. **Report.** End state, then a table of steps (status, expected, observed), the record path, and the human-only steps with what the user should do.

## Rules

- Never mark a human-only step as passed.
- Never invent element names or bundle ids; read them from the screen or the project.
- `--same-screen` is only for a step whose expected result is no change.
- Apple's documentation and the tapping tool's own documentation are the source for how to drive the simulator.

## Not for

- One screen after launch → use `sim-proof`.
- Flows in a web browser → use `qa-run`.
- Writing up a bug found on the way → use `bug-report`.

## Level

- beginner: explain why each step needs a screenshot and what "human" steps are.
- standard: as written.
- expert: the step table and the RESULT line only. No step is accepted without evidence at any level.

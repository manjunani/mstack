---
name: qa-run
description: Drives a running app through the user flows a change touched and writes a QA report in which every issue has steps, expected, actual and a saved evidence file. Use when a web app change is ready to be tried by hand, or the user says QA this, test it in the browser, click through the app or dogfood the branch. Reports only. Not for fixing what it finds (use debug), judging how a page looks (use design-review) or checking an API that has no screen (use api-check).
license: MIT
metadata:
  pack: test
  version: 0.3.0
  needs: python3, a browser tool of the host agent, git (optional)
---

# QA run

Produces `.mstack/qa/report.json`: one row per scenario with a final state, and one complete entry per issue, checked by a script.

## Done when

- Every scenario in the report is `pass`, `fail`, `skipped` (with the reason) or `blocked` (with what a person has to do). None was dropped.
- Every issue has steps, expected, actual, a severity and an evidence file that exists and is not empty.
- The project's test suite result is in the report, or the reason it was not run.
- `report.py check` printed the end state, and the reply repeats it without upgrading it.

End in exactly one state: **pass**, **fail** (issues found, an incomplete report, or a red suite), **not verified** (say which scenarios were skipped or which check did not run), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| A browser tool | Your own tool list has a tool that can open a URL, click, type, read the page and save a screenshot | Tell the user that this skill drives the app through the host agent's browser tool and none is connected; name the kinds that work (a built-in browser pane, a Playwright or Chrome DevTools connection). Install nothing. End as blocked |
| A way to start the app | The user's command, or the `dev` / `start` script in the project files | ask the user; end as blocked if there is none |
| git | `git rev-parse --is-inside-work-tree` | carry on; ask the user which screens changed |

This skill ships no browser. Reading the source or calling URLs with curl is not a replacement: without a browser tool the result is blocked, not a weaker pass.

## Steps

The scripts are `scripts/server.py` and `scripts/report.py` in this skill's folder. In Claude Code the folder is `"${CLAUDE_SKILL_DIR}"`. Run each with `--help` for the full options.

1. **Check needs.** Stop here as blocked when there is no browser tool.
2. **Create the report and read the scope.**
   ```
   python3 scripts/report.py init --title "<what changed>" --base <main branch> --driver "<browser tool name>"
   ```
   It lists the files the change touched. For a whole-app run the user asked for, add `--whole-app`. If the change touches no user flow, run `init` with `--nothing-to-test "<reason>"` and go to step 8.
3. **Write the scenarios before opening the app.** Map each changed file to the user flows that pass through it. One scenario is one path through a flow: where the user starts, what they do, what they see, where they land, and what is still true after a reload. Add at least one path where the user does something wrong (empty field, bad value, back button).
   ```
   python3 scripts/report.py scenario S1 --flow checkout --name "add an item, reload, cart still shows 1 item"
   ```
4. **Start the app.**
   ```
   python3 scripts/server.py start --name web --port 3000 -- <the start command>
   ```
   Exit 2 with "already accepts connections" means something else holds the port. If that is the app the user already runs, use `server.py wait --port 3000`. Do not stop it.
5. **Drive each scenario** with the browser tool, in order. Look at the page before acting. After each one, record its state at once, so an interrupted run can go on from the file:
   ```
   python3 scripts/report.py scenario S1 --state pass
   python3 scripts/report.py scenario S4 --state blocked --reason "needs a test account from the owner"
   ```
6. **When something is wrong, stop and capture it first.** Save a screenshot (and the console or network error text, if any) under `.mstack/qa/evidence/` while the fault is on screen. Then:
   ```
   python3 scripts/report.py issue --scenario S2 --severity high --title "<one line>" \
     --step "<step 1>" --step "<step 2>" --expected "<what should happen>" --actual "<what happened>" \
     --evidence evidence/s2-cart.png
   ```
   Evidence paths are relative to the report's folder. Then continue with the next scenario.
7. **Record the test suite and stop the app.**
   ```
   python3 scripts/report.py suite -- <the project's test command>
   python3 scripts/server.py stop --name web
   ```
   If there is no test command, use `suite --not-run "<reason>"`.
8. **Check.**
   ```
   python3 scripts/report.py check
   python3 scripts/report.py render
   ```
   Fix every `incomplete:` line by adding what is missing, never by deleting the scenario or the issue.
9. **Report.** The end state from `check` first. Then the issues, worst first, each with its evidence path; then scenarios that were skipped or blocked and why; then the suite result and where the report is.

## Rules

- This skill changes no application code. An issue goes into the report, however small the fix looks.
- A scenario passes when its end result was seen in the browser. A success message alone is not the end result: reload or open the destination and look.
- A scenario that could not be reached stays in the report as `skipped` or `blocked`. Leaving it out is the failure this skill exists to prevent.
- Use one browser tool for the whole run.
- Evidence is saved when the fault is seen. Do not recreate it later, and do not describe a screenshot that was not saved.
- Scenarios that pass while the test suite is red end as fail.
- Test against a local or test deployment. Sending mail, paying, or changing real data on a live site needs the user's yes for that action.
- Sign in with test accounts from the project's seed or example files. A login that needs a real person's password makes the scenario `blocked`.
- `server.py stop` stops only what `server.py start` started.

## Not for

- Fixing an issue it found → use `debug`, then `build`.
- Whether a page looks right at each width and theme → use `design-review`.
- Keyboard and screen reader checks → use `a11y-audit`.
- An API with no screen → use `api-check`.
- Proving the project's own checks pass → use `verify`.
- Writing up one bug the user already knows about → use `bug-report`.

If a named skill is not installed, say so and leave that part to the user; do not do its job here.

## Level

- beginner: explain the scenario list before driving it, and what each state means; show the first issue entry in full.
- standard: as written.
- expert: the reply is the end state, the issue list and the open scenarios. Every scenario still gets a state and `check` still runs.

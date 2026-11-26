---
name: bug-report
description: Confirms a bug reproduces from a clean start, saves the output as evidence, and writes one report that a lint script checks for steps, expected, actual, evidence files and leaked secrets or personal data. Use when the user wants to file, write up or report a bug, open an issue for a crash, or asks whether a reported bug is real. Not for finding the cause or fixing it (use debug) or for testing a whole flow to find bugs (use qa-run).
license: MIT
metadata:
  pack: test
  version: 0.3.0
  needs: python3, a command or steps that show the bug
---

# Bug report

Produces evidence under `.mstack/bugs/<id>/` from a clean reproduction, and one Markdown report that passes the lint.

## Done when

- `bugrep.py repro` ran from a clean start and recorded reproduced, not reproduced or intermittent, with the output saved.
- The report has Summary, Steps to reproduce (numbered), Expected, Actual, Environment and Evidence, and `bugrep.py lint` passes.
- Nothing was posted anywhere. Filing the report is the user's step, or happens after their yes.

End in exactly one state: **pass** (reproduced, report lints clean), **fail** (not reproduced, or the lint finds problems), **not verified** (intermittent, or the clean start could not be made; say which), or **blocked** (say what the user has to provide).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| A way to show the bug | A command, a test, or steps the user gave | ask for the steps; if they need a browser, use `qa-run` to capture them |
| A marker | Text that appears only when the bug happens, or the wrong exit code | ask the user what they saw; end as blocked without one |

## Steps

The script is `scripts/bugrep.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/bugrep.py"`.

1. **Write down what the user saw**, in their words. What they did not say is `unknown`; do not fill it in.
2. **Reproduce from a clean start.**
   ```
   python3 scripts/bugrep.py repro --id <short-name> --clean "<command that resets state>" \
     --command "<reproduction command>" --expect "<text only the bug prints>" --runs 3
   ```
   The clean step is a fresh build, an empty test database or a new temp profile, never a deletion of the user's data. If no clean step is possible, leave it out and say the start was not clean.
3. **Read the result.** Not reproduced: report that, with the evidence, and ask the user for what differs (version, data, settings). Intermittent: say so; `flaky-triage` can pin it down if installed.
4. **Write the report** to `.mstack/bugs/<id>/report.md` with the six sections. Steps are a numbered list someone else can follow. Expected and Actual are specific. Environment names versions and the commit, or `unknown`. Evidence lists the saved log files, relative to the report.
5. **Lint.**
   ```
   python3 scripts/bugrep.py lint .mstack/bugs/<id>/report.md
   ```
   Replace any token, password, email or phone number it finds with `<redacted>` or an example value. Lint again until it passes.
6. **Report.** End state first. Then the reproduction result, the report path, and how to file it. Posting to a tracker (for example `gh issue create`) happens only after the user says yes to that report and that place.

## Rules

- A non-zero exit alone is not the bug. The marker has to appear.
- One bug per report. A second fault found on the way gets its own report.
- Keep the reporter's uncertainty: `unknown` is better than a guess.
- Evidence is the saved output of a real run, never text written to look like one.
- Do not look for the cause in this skill. A suspected cause can go in the report, labelled as a guess.
- Never paste a real customer's data into a report. Use example values.

## Not for

- Finding the cause or fixing the bug → use `debug`.
- Clicking through flows to find bugs → use `qa-run`.
- A bug that shows up only sometimes → use `flaky-triage` first.
- Proving a fix is done → use `verify`.

If a named skill is not installed, say so and stop at the report.

## Level

- beginner: explain why a clean start matters and what each report section is for.
- standard: as written.
- expert: the reply is the end state, the reproduction line and the report path. Repro and lint still run.

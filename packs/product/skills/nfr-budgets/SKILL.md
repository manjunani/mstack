---
name: nfr-budgets
description: Turns quality words such as fast, reliable or secure into budgets that a command can check. Each has a metric, a number, a unit, a condition and a check command, and every command is run. Use when a requirement says fast, scalable, reliable or secure with no number, when the user asks "how fast is fast enough", or wants performance, size or error limits that fail loudly. Not for functional requirements (use spec), for proving the tests pass (use verify) or for judging code quality (use review).
license: MIT
metadata:
  pack: product
  version: 0.2.2
  needs: python3, a project with commands that can be run
---

# NFR budgets

Produces `.mstack/budgets.json` and a run record: for each quality word, a measured value beside its limit, as pass, fail or not verified.

## Done when

- Every budget has metric, number, unit, condition and check command. `scripts/budgets.py` refuses the file otherwise.
- A baseline was recorded before any number was set.
- `scripts/budgets.py check` ran every command; the reply reports each budget as it was printed.

End in exactly one state: **pass**, **fail** (the budgets over their limit are shown with value and limit), **not verified** (say which value could not be read and why), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| Something to measure with | the project has a command that produces the value: a test run, a build, a benchmark script, an audit tool | say which measurement has no command and end as blocked for that budget; do not write a number nobody can check |
| The tool each command uses | `budgets.py baseline` reports `tool not found` | tell the user which tool and how to get it; that budget is not verified |

## Steps

The script is `scripts/budgets.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/budgets.py"`.

1. **Collect the quality words** from the request or the spec, one line each.
2. **Choose a metric for each.** Ask what a person would notice if it went wrong, then find the command that measures that.

   | Word | Kinds of metric | Read as |
   |---|---|---|
   | fast | time of one named operation; size of a build output | `duration`, or `output` of a size command |
   | reliable | failures in N repeated runs; error count from a test run | `output` |
   | secure | findings at a named severity from the project's audit tool | `output`, or `exit` |
   | scalable | the same timing at a named data size | `duration` |

3. **Write the budgets without numbers.**
   ```
   python3 scripts/budgets.py template
   ```
   Fill in metric, unit, condition, check and measure for each. The condition says where and on what data the value holds.
4. **Show the commands and wait for a yes.** They will be executed.
   ```
   python3 scripts/budgets.py list
   ```
5. **Measure what is true today.** Use three or more runs for timings.
   ```
   python3 scripts/budgets.py baseline --runs 3
   ```
6. **Set each number with the user.** Show the baseline value, say what the user's need implies, propose a number and let the user decide. Write it into the file.
7. **Run the checks.**
   ```
   python3 scripts/budgets.py check --runs 3
   python3 scripts/budgets.py check B-02        # one budget
   ```
8. **Report.** End state first. Then one line per budget: metric, value, limit, baseline, condition, verdict. Then what the budgets do not cover.

## Rules

- A number comes from the baseline and the user's need. A figure you remember from elsewhere is a suggestion: say it is unverified and where you believe it comes from.
- Never loosen a number to get a pass. A limit the project fails today is a target; report it as fail and let the user decide.
- A value holds only under its condition. A laptop timing says nothing about the server; write the condition that was really measured.
- A check command that reaches another machine uses only the address the user gave, after a yes, and never puts load on production.
- "Secure" is budgeted only for what a tool counts. Say plainly that a clean audit is not a security review.
- The script refuses commands that delete, reset, push or use raised rights. Do not rewrite a command to get round the refusal; ask the user for a read-only way to measure.
- If the spec has ids, offer one `measure` line per budget for it; do not edit the spec without a yes.

## Not for

- What the software does, as numbered requirements → use `spec`.
- Running the project's tests, lint and build to prove a "done" claim → use `verify`.
- Judging whether the code is well made → use `review`.
- Deciding which tests are missing → use `test-gaps`.

## Level

- beginner: explain metric, condition and baseline with the first budget as the example, and what "not verified" means for a value.
- standard: as written.
- expert: propose all metrics in one table and ask once. The command confirmation, the baseline and the check run happen at every level.

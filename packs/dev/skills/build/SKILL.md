---
name: build
description: Carries out a plan task by task and keeps a ledger in which a task is logged complete only when its own test command passes and no file outside its list changed. Use when a plan or a clear multi-step request is ready and the user says implement it, build it, start on task 1 or continue the plan. Not for writing the plan (use plan), finding why something fails (use debug) or a one-line edit that needs no ledger.
license: MIT
metadata:
  pack: dev
  version: 0.1.0
  needs: python3, git, the project's test runner
---

# Build

Produces working code for each task of a plan and a ledger file that proves which tasks are done, on which commits.

## Done when

- Every task has a completion line written by `ledger.py done`.
- `ledger.py finish` ran the full suite once and it passed on the final commit.
- One review of the whole range was recorded with `ledger.py reviewed`.
- `ledger.py status` prints `RESULT pass`.

End in exactly one state: **pass**, **fail** (show the failing check output), **not verified** (say which task, suite run or review is missing), or **blocked** (say what the user must decide).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| git with one commit | `git rev-parse HEAD` | end as blocked: the ledger ties tasks to commits |
| A plan with files and a check per task | `.mstack/plans/<name>.md` exists | use `plan` to write one; for a small clear request give `--files` and `--check` to `start` instead |
| The full test command | ask the user, or read it from the project's README, CI file or `.mstack/checks.json` | end as blocked; never invent a command |

## Steps

The script is `scripts/ledger.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/ledger.py"`.

1. **Check needs.** Run `python3 scripts/ledger.py status`. If a ledger exists, continue from the first task that is not done; do not start over.
2. **Start the task.**
   ```
   python3 scripts/ledger.py start <n> --plan .mstack/plans/<name>.md
   ```
   It prints the files the task may touch and its check. Add `--review per-task` on the first start only when the user asks for a review after each task (risky work: money, auth, data migration).
3. **Fit the codebase before writing.** Read the files in the list and one nearby example. Then, in this order: is the change needed at all; does this codebase already have it; does the standard library or an installed dependency do it; only then write new code, in the style of the file you are in. No new dependency without asking.
4. **Write the task.** Touch only the listed files. Write or extend the task's test first when the plan's check is a test.
5. **Close the task.**
   ```
   python3 scripts/ledger.py done <n>
   ```
   - Exit 1 with check output: fix the code and run `done` again. After three failed attempts on one task, stop and use `debug`.
   - Exit 1 with `outside:` lines: undo those edits, or ask the user whether they belong; only with a yes repeat with `--accept-outside "<reason>"`.
   - Exit 2: the check could not run. Report that; do not swap in another command.
6. **Commit the task** (use `commit` if installed, otherwise one commit naming only the task's files), then go to step 2 for the next task. Do not pause between tasks unless a task is blocked.
7. **Finish.** After the last task:
   ```
   python3 scripts/ledger.py finish --suite "<full test command>"
   ```
   If it fails, name every failing test, including ones this build did not touch, and fix what this build broke.
8. **Review once.** Review the range `finish` printed, using `review` (give it that exact range). Fix critical and important findings, run `finish` again, then:
   ```
   python3 scripts/ledger.py reviewed --findings <findings file>
   ```
9. **Report.** Run `python3 scripts/ledger.py status` and state its result first, then tasks done, outside files that were accepted and why, and anything not verified.

## Rules

- Only `ledger.py done` may write a completion line. Never edit the ledger by hand, and never say a task is done without it.
- Never change a task's check, delete a test or loosen an assertion to get a pass. If the check is wrong, stop and tell the user.
- A deliberate shortcut gets a comment that starts with `SHORTCUT:` and says what was skipped; list those in the report.
- If the plan turns out wrong (a file is missing from a task, the order cannot work), stop, fix the plan with the user, then `start --restart`.
- Per-task mode costs one review per task. Say that before choosing it.

## Not for

- Turning a request into tasks → use `plan`.
- A failure whose cause is unknown → use `debug`.
- Running tasks at the same time in separate worktrees → use `parallel`.
- Proving one test can catch its bug → use `prove-test`.

## Level

- beginner: before each task, say in two sentences what it changes and how its check proves it; explain a failed check in plain words.
- standard: as written.
- expert: report only the status output and accepted outside files. No check, suite run or review is skipped at any level.

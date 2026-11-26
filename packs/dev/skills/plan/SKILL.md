---
name: plan
description: Turns a settled request into a plan file of small ordered tasks, each a brief a fresh agent can carry out alone: its files, the context it needs, one check command and the output to expect; then lints the plan. Use when work touches several files or steps and the user asks to plan it, lay it out before coding, list the steps, break it down or turn a ticket into a task list, write an implementation plan, or asks "how would you build this" before any code. Not for deciding what to build (use clarify or spec) or for carrying the plan out (use build).
license: MIT
metadata:
  pack: dev
  version: 0.3.0
  needs: python3, git
---

# Plan

Produces one plan file whose every task is a standalone brief, and a lint result that says the plan is complete. `build` hands each task to a fresh agent that sees only the plan header and that one task, never the conversation.

## Done when

- `plan_lint.py lint` exits 0 on the plan file.
- The user read the plan and approved it.
- No project file was changed. The only new file is the plan.

End in exactly one state: **pass**, **fail** (the lint still reports problems; show them), **not verified** (the lint could not run; say why), or **blocked** (a question only the user can answer; ask it).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| git | `git rev-parse --is-inside-work-tree` | carry on; the lint then searches the folder without git's ignore rules |
| A settled request | You can state the goal and what is out of scope in two sentences | end as blocked with the open question; `clarify` or `spec` settle it, if installed |

## Steps

The script is `scripts/plan_lint.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/plan_lint.py"`.

1. **Check needs.** If a question remains whose answer changes what gets built, ask that one question and stop.
2. **Pick the size.** One file and one check: say the steps in the reply, write no file, end as pass with that reason. Otherwise write a plan file.
3. **Read the code first.** Open every file the work will touch and the nearest existing example of the same kind of change. Note the real names: functions, types, tables, routes, test commands.
4. **Write the plan** to `.mstack/plans/<short-name>.md`, starting from `assets/plan-template.md`.
   - A task is one change a reviewer could accept alone. Order tasks so each one's check can pass when it is reached.
   - `Files` lists every file the task may touch; a file the task creates gets `(new)`.
   - `Context` holds what a builder who never saw the conversation must know: decisions made, formats, the reason for the change. Write `none` when the files, steps and check already say it all. Never write "as discussed" or "see above": write the thing itself.
   - `Uses` and `Makes` carry the exact names that cross from one task to another.
   - `Check` is one command. `Expect` is what it prints when the task is right.
   - Copy the user's limits word for word into the header.
5. **Lint.**
   ```
   python3 scripts/plan_lint.py lint .mstack/plans/<short-name>.md
   ```
   Fix every `FAIL` line in the plan and run again. Read each `warn` line and either act on it or tell the user why not.
6. **See what a builder sees.**
   ```
   python3 scripts/plan_lint.py tasks .mstack/plans/<short-name>.md
   ```
   Read each task as a fresh agent would: only the header, that task's fields and its numbered steps. If it cannot be done from that alone, the plan is missing a decision. Add it to that task's `Context` or steps.
7. **Ask.** Show the plan path, the task titles and any warnings. Wait for approval or changes.
8. **Report.** End state first, then the plan path, the number of tasks, warnings left, and what the plan does not cover.

## Rules

- Every task stands alone. A builder gets the plan header and one task, nothing else; anything it needs from the conversation goes into that task.
- The plan holds decisions the builder cannot make alone: order, names, file boundaries, checks. It leaves out what the code and the test already decide.
- Write code in the plan only where a signature and a check do not settle the shape.
- A check that cannot fail proves nothing. Prefer a test that exercises the new behaviour over "the module loads".
- If the lint says a name is not in the project, check the spelling in the code before changing the plan.
- Planning changes no code and runs no build. When the user says "go", that is the next skill's work.

## Not for

- Finding out what the user wants → use `clarify`, or `spec` for a written one-pager. If neither is installed, ask the open questions one at a time yourself.
- Carrying out the plan → use `build`.
- Splitting tasks across agents → use `parallel`, after the plan passes.

## Level

- beginner: explain each field of the first task and why a check must be able to fail; ask before choosing the size.
- standard: as written.
- expert: show the task titles and warnings only. The lint and the approval are never skipped.

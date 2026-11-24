---
name: spec
description: Writes a one-page spec in which every "done when" line has an id (R-001) and names how it will be checked, then lints it. Use when the goal is clear and needs writing down before building, when the user asks for requirements, acceptance criteria or a PRD, or wants a spec of what existing code already does. Not for finding out what the user wants (use clarify), for ordering the work into tasks (use plan) or for deriving test cases (use test-cases).
license: MIT
metadata:
  pack: product
  version: 0.2.2
  needs: python3
---

# Spec

Produces one Markdown file: a goal, numbered requirements that each name their check, and a list of what is left out.

## Done when

- `scripts/speclint.py check` exits 0 on the spec: the required parts are present, ids are unique, every line names a check method and how, there is no vague word, no placeholder and no open question.
- For a spec written from existing code, the same check with `--from-code` exits 0: every line cites a file that exists.
- The user read the file and approved it.

End in exactly one state: **pass**, **fail** (the linter's failing lines are shown), **not verified** (say which check did not run), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| A settled goal | the conversation or an intent file states who it is for, the outcome, what success looks like and what is out | use `clarify` if installed; otherwise ask the user for the one missing point; end as blocked until it is answered |

## Steps

The script is `scripts/speclint.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/speclint.py"`. Put the spec where the project keeps such files; if it has no place, use `docs/specs/<short-name>.md`.

1. **Size the work.** One behaviour in one place needs no file: write its "done when" lines in the reply, with ids and checks, and end as pass.
2. **Start the file.**
   ```
   python3 scripts/speclint.py template docs/specs/<short-name>.md --title "<the work>"
   ```
3. **Write the requirements.** One observable result per line, in the shape the linter reads:
   ```
   - R-001: <when this happens, this is observed> Check: <method>: <how>
   ```

   | Method | Use it when | "how" says |
   |---|---|---|
   | `test` | an automated test can decide it | the test file or test name |
   | `command` | a command's result decides it | the command |
   | `measure` | a number decides it | what is measured, and the limit with its unit |
   | `inspect` | a person looks at a result | what to open and what to see |
   | `demo` | a person walks through steps | the steps |

4. **Write "Not doing".** At least one thing a reader might expect and will not get.
5. **Lint.** Fix the spec until it passes. Warnings are for you to judge.
   ```
   python3 scripts/speclint.py check docs/specs/<short-name>.md
   ```
6. **Get approval.** Show the file to the user. Edits after approval mean a new lint run.
7. **Report.** End state first, then the path, the number of requirements, the warnings you left in and why.

### Second mode: the spec that existing code implies

Use it when a project has code and no spec, so that `trace` has ids to work with.

1. List the places to read. This prints routes, commands, options and tests with `file:line`.
   ```
   python3 scripts/speclint.py survey
   ```
2. Open each file before writing about it. Write a line only for behaviour you read, and end the line with `Source: <path>:<line>`.
3. Lint with the source check.
   ```
   python3 scripts/speclint.py check docs/specs/<short-name>.md --from-code
   ```
4. Describe what the code does, not what it ought to do. Report suspected bugs in the reply, not as requirements.

## Rules

- An id is never reused and never renumbered. A removed requirement retires its id; a changed meaning gets a new one. The linter prints the next free id.
- A requirement says what is observed, not how it is built. Name a library or a class only when the user set it as a constraint.
- When the linter rejects a word, replace it with what a person would see or measure. Do not edit the word list to get a pass, and do not hide prose in backticks.
- A quality word that needs a measured limit ("fast", "reliable", "secure") goes to `nfr-budgets` if installed; otherwise ask the user for the number and its condition.
- This skill does not interview and does not plan tasks. A missing decision ends it as blocked.

## Not for

- The goal or the reason is still unclear → use `clarify`.
- Turning an approved spec into ordered tasks → use `plan`.
- Deriving test cases from the acceptance lines → use `test-cases`.
- Showing which tests and code cover each id → use `trace`.
- Checking that finished work meets the spec → use `verify`.

## Level

- beginner: explain what makes a line checkable, and show one rejected line beside its rewrite.
- standard: as written.
- expert: no explanations; the file, the lint result and the question "approved?". The lint and the approval happen at every level.

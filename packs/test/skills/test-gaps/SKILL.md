---
name: test-gaps
description: Finds what matters and is not tested. Counts test files, detects runners and CI, and lists recently changed source files and folders that no test names or imports, then records one decision per top risk. Use when the user asks what is untested, where tests are missing, whether the tests are good enough, or what to test first in an existing codebase. Not for tracing spec requirements to tests (use trace), designing cases for one feature (use test-cases) or checking that one test can fail (use prove-test).
license: MIT
metadata:
  pack: test
  version: 0.2.0
  needs: python3, git (for recent changes)
---

# Test gaps

Produces `.mstack/test-gaps/inventory.json` and a gap table in which every top risk has a named test or a stated reason for none.

## Done when

- `inventory.py scan` ran on the project and its output was read, including the runner and CI lines.
- Every row of the gap table has a risk in the user's terms and one action: `add`, `update`, `keep`, `delete` or `no-test`.
- Every `add`, `update` and `keep` names a test; every `no-test` and `delete` has a reason.
- `inventory.py check` printed the end state. Tests that are decided but not written leave it at not verified.

End in exactly one state: **pass** (every top risk has a test that exists or a reason; or the scan found no gap), **fail** (rows are incomplete or a risk was dropped), **not verified** (decided tests are not written yet, or there is no git history; say which), or **blocked** (say which decision only the user can make).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| git | `git rev-parse --is-inside-work-tree` | carry on: files are ranked by size, and the report says that recent change is not verified |

## Steps

The script is `scripts/inventory.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/inventory.py"`.

1. **Scan.**
   ```
   python3 scripts/inventory.py scan                 # --since-days 90 --top 10 are the defaults
   ```
   It prints the counts, the runners and CI config it found, the changed source files no test names or imports, and the folders with no such file at all. It writes a gap table with one row per top risk.
2. **Read the top of the output first.** No runner, test files nothing can run, no CI config, or CI that never runs a test command: each of these outranks any single file. Add it as a row.
3. **Check each lead.** Open every file in the gap table. The script judges by file names and import lines, so:
   - a listed file may be exercised through another module: find the test that does it and use `keep` with that test;
   - a file that is not listed may be imported and still have its main behaviour unasserted: add a row for it.
4. **Ask what hurts.** Ask the user which failures would cost most (money, lost data, sign-in, anything legal). Add a row for each one the table does not already hold. Risk comes from the user and the code, not from line counts.
5. **Decide every row** in the gap file.

   | Action | Use when | The row needs |
   |---|---|---|
   | `add` | A real risk has no test | `test`: the file and name the test will have, as `path::name` |
   | `update` | A test exists and misses the risky case | `test`: the existing test |
   | `keep` | The lead was wrong: a test covers it | `test`: that test |
   | `delete` | A test checks nothing or checks a removed feature | `test` and a `reason`; removing it is the user's call, through `safe-delete` |
   | `no-test` | Testing costs more than the fault would | `reason`: generated code, about to be removed, covered by a named manual check |

   In the `risk` column write what goes wrong for a user, for example "customers are charged the wrong tax". Do not remove rows.
6. **Check.**
   ```
   python3 scripts/inventory.py check                # add --gaps <file> when the scan wrote gaps-2.md or later
   ```
   `problem:` lines are rows to complete. `pending:` lines are tests that were decided and do not exist yet.
7. **Report.** End state first. Then the runner and CI findings, the table with its decisions, the pending tests in the order they should be written, and what was not verified.

## Rules

- This skill decides; it does not write tests. Writing the `add` rows is a task for `build`, and the end state stays not verified until those tests exist.
- State no coverage percentage. The script measures none, and a percentage is not the goal.
- "Named or imported by a test" is a lead, not proof of testing. "Not named" is a lead, not proof of a gap. Say which rows were confirmed by reading.
- Two tests that touch the same code are not proof that one is redundant.
- `no-test` is a valid decision when the reason is real. Do not add tests to make the table look complete.
- Every `add` row names the fault the test would catch, in the risk column.

## Not for

- Which spec requirement has no test → use `trace`.
- The cases one feature needs → use `test-cases`.
- Whether an existing test can fail at all → use `prove-test`.
- Writing the missing tests → use `build`.
- Trying the running app by hand → use `qa-run`.

If a named skill is not installed, say so and hand the row list to the user.

## Level

- beginner: explain what a runner and CI are when one is missing, and why a file without a test may still be fine.
- standard: as written.
- expert: the reply is the end state, the gap table and the pending list. The scan and the check still run.

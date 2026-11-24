---
name: test-cases
description: Turns a spec or a function contract into a table of test cases (boundaries, combinations, properties) in which every requirement has a case and every case has one specific expected result. Use when the user asks what to test, wants test cases, edge cases or a test matrix for a feature, form or function, or a spec with R-001 style lines has no cases yet. Not for writing the test code (use build), writing the spec itself (use spec) or mapping requirements to tests that already exist (use trace).
license: MIT
metadata:
  pack: test
  version: 0.2.1
  needs: python3, a spec or contract with requirement lines
---

# Test cases

Produces one Markdown case table beside the spec, checked line by line against the spec's requirement ids.

## Done when

- `cases.py check` passes: every requirement line (`R-001` form) has at least one case, every case names the requirement it covers, and every case has exactly one specific expected result.
- Rows for combined options came from `pairwise.py`, not from picking by hand.
- Every expected result comes from the spec or from the user. Questions the spec does not answer are listed for the user, not filled in.

End in exactly one state: **pass**, **fail** (the checker lists problems that are left), **not verified** (say what could not be checked, for example a spec with no requirement ids), or **blocked** (say which expected results only the user can give).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| Requirement lines | `python3 scripts/cases.py ids --spec <file>` lists at least one | See step 1 |

## Steps

The scripts are `scripts/cases.py` and `scripts/pairwise.py` in this skill's folder. In Claude Code the folder is `"${CLAUDE_SKILL_DIR}"`.

1. **Find the requirement lines.**
   ```
   python3 scripts/cases.py ids --spec <spec file>
   ```
   A requirement line starts with an id such as `R-001`. If the spec has none: use `spec` when it is installed. Otherwise copy the acceptance lines into a new file `<name>.contract.md`, give each an id, and show it to the user. Do not edit the user's spec. For a function with no spec, write its contract the same way: one line per promise (inputs accepted, result, errors), and have the user confirm it.
2. **Choose a technique for each requirement.** Read `references/techniques.md` now. In short: a limit needs boundary cases; three or more independent options need combination rows; a rule that turns one value into another may have a property.
3. **Generate combination rows** where step 2 says so.
   ```
   python3 scripts/pairwise.py --param "plan=free,pro,team" --param "region=eu,us,in" --param "sso=on,off" \
     --exclude "plan=free,sso=on" --covers R-004 --out <name>.pairs.md
   ```
   The script recounts the pairs from the finished rows and prints how many rows stand in for how many combinations. Its `expected` column is empty on purpose.
4. **Write the case table** in a new file next to the spec, `<name>.cases.md`. Columns: `id`, `covers`, one column per input, `expected`. Paste generated rows in. Several tables with different input columns are fine.
5. **Fill each expected result** with something a test can observe: the value returned, the status, the exact message, the stored state. Take it from the spec. If the spec does not say what happens, do not read it off the current code, because the code may be the fault: put the question on a list for the user and leave the case out until it is answered.
6. **Check.**
   ```
   python3 scripts/cases.py check --spec <spec file> --cases <name>.cases.md
   ```
   Fix each `problem:` line. A case that allows two results is split, or the right one is chosen. A requirement with no case gets one, or the user says why it cannot be tested, and that reason is reported.
7. **Report.** End state first. Then the number of requirements and cases, which technique was used where, the open questions for the user, and the path of the table.

## Rules

- One case, one expected result. "400 or 422" accepts a fault; so does "works".
- Before keeping a case, name the fault that would make it fail. If there is none, drop the case. There is no target count.
- Never invent an expected result to make the checker pass. An unanswered question ends as blocked.
- Pairwise rows cover every pair of values. A combination of three specific values that the spec names is added by hand.
- Where a wrong result costs money, access or data, use all combinations for that parameter and say so.
- A property is written as the expected result with the class of inputs it holds for. "No property fits" is a valid outcome.
- This skill writes cases, not test code, and never changes the spec.

## Not for

- Writing the tests from the table, test first → use `build`.
- Writing or repairing the spec → use `spec`.
- Finding which requirements already have tests in the code → use `trace`.
- Finding untested code where there is no spec → use `test-gaps`.
- Showing that one finished test can fail → use `prove-test`.

If a named skill is not installed, say so; the case table is still complete without it.

## Level

- beginner: explain why each technique was chosen and show two or three cases before writing the rest.
- standard: as written.
- expert: the reply is the end state, the counts, the open questions and the path. The checker still runs.

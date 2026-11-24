---
name: data-check
description: Runs written rules against a dataset like tests (not null, unique, allowed values, range, pattern, row count, foreign key into another file) and reports each rule as pass, fail or not run, with the failing row numbers. Use when data has to meet agreed rules before loading, publishing or handing over, or the user asks "does this file meet the spec" or wants a data quality gate. Not for a first look at an unknown file (use data-profile) or for fixing values (use data-clean).
license: MIT
metadata:
  pack: data
  version: 0.2.2
  needs: python3
---

# Data check

Produces a verdict per rule, with the rows that break it, from a rules file kept beside the data.

## Done when

- A rules file exists and the user agreed with its rules.
- `scripts/check.py` ran and every rule shows pass, fail or not run with a reason.
- Hard failures fail the run; soft rules only warn. Zero rows fails unless a rule allows it.

End in exactly one state: **pass** (every hard rule passed), **fail** (a hard rule failed; rows named), **not verified** (a rule could not run), or **blocked** (no usable rules file or dataset).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| A rules file | the path exists | step 2 writes one with the user |

## Steps

The script is `scripts/check.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/check.py"`.

1. **Check needs.** If the project already runs data tests (dbt tests, a validation library), run those and read their result instead of adding a second system.
2. **Write the rules** when there are none. Take them from the spec, the schema or the user's words; never invent a limit. Format and every field: `references/rules.md`. Save it next to the data, for example `.mstack/rules/orders.json`. Show it to the user before the first run. Mark a rule `"severity": "soft"` only when the user says a breach should warn, not stop.
3. **Run.**
   ```
   python3 scripts/check.py <rules.json> [--quarantine NEW_FILE.csv]
   ```
   `--quarantine` writes every failing row with the rule name to a new file, so it can be inspected without changing the data.
4. **Report.** End state first. Then failing rules with counts and row numbers, then rules not run and why, then passing rules in one line.

## Rules

- Never loosen a rule, change a limit or mark a rule soft to get a pass. A rule changes only when the user changes it.
- A rule that could not run is not a pass.
- Empty values pass every rule except `not_null`; say so when a column has many empties.
- Do not fix data here. Failing rows go to the user or to `data-clean`.

## Not for

- A first look at a file nobody has described → use `data-profile`.
- Fixing the failing values → use `data-clean`.
- Checking that a schema migration is safe → use `migration-check`.

## Level

- beginner: explain each rule in a sentence before the run, and what hard and soft mean.
- standard: as written.
- expert: the RESULT line and the failing rules only. Every rule still runs.

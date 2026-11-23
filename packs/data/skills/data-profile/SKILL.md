---
name: data-profile
description: Describes a CSV, JSON-lines file or SQLite table as it really is, giving row count, per-column type, empty share, distinct count, min and max, top values, duplicate rows, and columns that look like identifiers or personal data. Use when someone hands over a dataset, asks "what's in this file", or before trusting, analysing or sharing data nobody has looked at yet. Not for checking data against written rules (use data-check) or comparing two versions (use data-diff).
license: MIT
metadata:
  pack: data
  version: 0.2.0
  needs: python3
---

# Data profile

Produces one profile of a dataset, printed by a script, with findings kept apart from what was fine and what was not read.

## Done when

- `scripts/profile.py` ran on the dataset and its RESULT line is in the reply.
- Every finding in the reply is a line the script printed; no column is described from a guess.
- Rows left unread (the row cap) are stated, and the source file is untouched (the script only reads).

End in exactly one state: **pass** (profile made, no structural fault; warnings listed), **fail** (no rows, wrong field counts, lines that do not parse), **not verified** (rows were left unread), or **blocked** (unreadable file, SQLite table not named).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| The dataset | the path exists | ask for it; end as blocked |

## Steps

The script is `scripts/profile.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/profile.py"`.

1. **Check needs.**
2. **Profile.**
   ```
   python3 scripts/profile.py <file> [--table NAME] [--json NEW_FILE]
   ```
   The type is read from the first bytes, not the extension. A SQLite file with several tables needs `--table`. An `.xlsx` is refused: export the sheet to CSV, or use `sheet-audit` for its formulas.
3. **Read the three lists.** In order of weight:
   - *fail*: structure is broken; nothing else in the profile can be trusted until it is fixed.
   - Mixed types in a column, with the row numbers: often a text value such as "abc" or a typed comment.
   - Words that stand for missing ("N/A", "null", "-"): the empty share does not count them.
   - An identifier-like column with repeats; exact duplicate rows.
   - Personal data: top values are hidden by default. Do not pass `--show-personal` unless the user asks to see them.
4. **Report.** End state first. Then rows and columns, the findings with row numbers, then the "could not check" list. Say what the profile does not tell: whether values are correct, only how they are shaped.

## Rules

- Profiling describes; it fixes nothing. Cleaning is a separate step with its own log (`data-clean`).
- Do not paste rows of data into the reply. Counts, types and row numbers are enough.
- A large file is read up to the cap in `references/limits.json`; say that the rest was not read.
- Thresholds in `references/limits.json` are unverified defaults; the script prints that.

## Not for

- Checking the data against rules someone wrote → use `data-check`.
- What changed between two versions → use `data-diff`.
- Making fake data for tests → use `test-data`.

## Level

- beginner: explain what an identifier-like column and a mixed-type column mean, with the row numbers.
- standard: as written.
- expert: the RESULT line, the findings and the could-not-check list only. The script runs at every level.

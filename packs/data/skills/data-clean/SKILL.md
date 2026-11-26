---
name: data-clean
description: Cleans messy values in a CSV into a new file (trim, case, dates to ISO, exact duplicates, mapped codes such as UK and U.K. to GB, stated fills) and logs every change with before and after. Use when asked to clean, tidy, standardise, normalise, dedupe or fix messy values, country codes, names or dates in a CSV or spreadsheet export, or fix what a profile found. It never guesses a fill value. Not for finding the problems first (use data-profile) or for fake test data (use test-data).
license: MIT
metadata:
  pack: data
  version: 0.3.0
  needs: python3
---

# Data clean

Produces a cleaned copy, a change log of every cell changed, a file of removed rows with the reason, and proof that the log explains the copy.

## Done when

- The user agreed with the plan: which operations, on which columns, and every fill value and mapping.
- `scripts/clean.py` wrote three new files and printed that replaying the log gives the output exactly.
- Values that could not be cleaned as asked are listed with their rows.
- The input file is unchanged.

End in exactly one state: **pass** (written, log replays exactly; zero changes is a pass), **fail** (some values could not be cleaned, or the replay does not match), **not verified** (a check after cleaning, such as `data-check`, was not run), or **blocked** (a fill with no value, an unknown column, an existing output, a broken CSV).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| A CSV input | the path exists | export other formats to CSV first; end as blocked |

## Steps

The script is `scripts/clean.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/clean.py"`.

1. **Check needs.** If nobody has looked at the data, run `data-profile` first, if installed; otherwise read the first rows and count problems by hand.
2. **Write the plan** as JSON (`references/operations.md`). Fill values, mappings and date formats come from the user. Ask what an empty cell means; never pick a mean, a most common value or the previous row.
3. **Show the plan and get a yes.**
4. **Clean.**
   ```
   python3 scripts/clean.py <input.csv> --plan plan.json --out <NEW.csv>
   ```
   Writes `<NEW.csv>`, `<NEW.csv>.changes.csv` and `<NEW.csv>.removed.csv`.
5. **Check the result.** Run `data-check` on the output if rules exist; if not, say the cleaned data was not checked against rules.
6. **Report.** End state first. Then changes per operation, values left as they were and why, the three file paths, and what was not checked.

## Rules

- The input is never overwritten, and the script refuses to write over any existing file.
- Removed rows are kept with their reason. Nothing disappears without a line in the log.
- A date that two stated formats read as different days stays as it was. Ask the user which format the source used.
- Do not add an operation the user did not agree to because it "looks better".

## Not for

- Finding what is wrong → use `data-profile`.
- Making fake data for tests → use `test-data`.
- Changing a database schema → use `migration-check`.

## Level

- beginner: walk through each operation and show three log lines as an example.
- standard: as written.
- expert: the counts per operation, file paths and the RESULT line. The plan still needs a yes.

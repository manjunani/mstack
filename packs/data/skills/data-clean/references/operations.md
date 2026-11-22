# Operations for clean.py

The plan is `{"operations": [ ... ]}`, applied in the order written. Each operation is logged cell by cell.

| op | fields | does |
|---|---|---|
| `trim` | `columns`: list or `"*"` (default all) | removes spaces at the start and end |
| `case` | `columns`, `to`: `lower`, `upper` or `title` | changes letter case |
| `parse_date` | `columns`, `formats`: list of `strptime` formats | rewrites a date to `YYYY-MM-DD` when exactly one format reads it, or several read it as the same day; ISO values and empty cells are left alone |
| `map` | `column`, `values`: object of old to new | replaces exact matches only |
| `fill` | `column`, `value` | puts the stated value into empty cells (spaces count as empty) |
| `drop_duplicates` | `columns` (default all) | removes rows identical to an earlier row on those columns; each goes to the removed-rows file with the row it repeats |

Not offered, on purpose: filling with a mean, median, most common value or the previous row; dropping rows by a condition; fixing typos by similarity. Each of these guesses, and a guess needs a person's decision. Decide with the owner, then express the decision as a `map` or `fill` with a stated value.

Common date formats: `%d/%m/%Y` (31/12/2026), `%m/%d/%Y` (12/31/2026), `%d %b %Y` (31 Dec 2026), `%Y%m%d` (20261231). Give only the formats that really occur; giving both day-first and month-first makes every ambiguous date a reported problem, which is correct.

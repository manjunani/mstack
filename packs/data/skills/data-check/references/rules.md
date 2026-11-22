# Rules file for check.py

A JSON object with `dataset` and `rules`. Paths are relative to the rules file.

`dataset`: a path to a CSV, JSON-lines or SQLite file, or `{"path": "shop.sqlite", "table": "orders"}`.

Every rule has `type`. Optional on every rule: `name` (printed instead of the type), `severity` (`hard`, the default, fails the run; `soft` only warns).

| type | fields | fails a row when |
|---|---|---|
| `not_null` | `column` | the value is empty or missing |
| `unique` | `columns` (list) or `column` | the key repeats an earlier row; rows whose key is all empty are skipped (pair with `not_null`) |
| `in_set` | `column`, `values` | a filled value is not in the list (compared as text) |
| `range` | `column`, `min` and/or `max` | a filled value is below or above; numbers compare as numbers, and when `min`/`max` are text (ISO dates) values compare as text |
| `pattern` | `column`, `regex` | a filled value does not match the whole regex |
| `row_count` | `min` and/or `max` | the dataset has too few or too many rows (no row numbers) |
| `foreign_key` | `column`, `ref`, `ref_column` | a filled value is not found in the reference column; `ref` is a path or `{path, table}` |

Empty values pass every rule except `not_null`. Write `not_null` beside a rule when empty is not allowed.

A dataset with zero rows fails the run unless a `row_count` rule says `"min": 0`.

A rule that cannot run (unknown type, missing column, bad regex, unreadable reference) is listed under "could not check", and the run ends as not verified, never as pass.

Row numbers count data rows from 1; the header line is not counted. In a SQLite table they follow the table's natural read order.

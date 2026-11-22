# mstack-data: what was tested

Date: 2026-11-22. Python 3.14.0, SQLite 3.50.4, macOS. Standard library only; nothing installed, no network.

## How to repeat

```
python3 packs/data/tests/scripts/data_cases.py packs/data .testrun          # all skills
python3 packs/data/tests/scripts/data_cases.py packs/data .testrun --only sql-run
```

The script builds every fixture itself (CSV, JSON-lines, SQLite, .xlsx written with zipfile, .ipynb) in new folders
`.testrun/data-<name>/` and refuses to run if they exist. Each case states the expected exit code and text that must or
must not appear, and every output's last line must be a RESULT or blocked line that fits the exit code.

Last run: **191 checks, 0 wrong** (output kept in `.testrun/data-cases-output.txt`).

| Skill | Checks | Wrong |
|---|---|---|
| data-profile | 21 | 0 |
| data-check | 13 | 0 |
| sql-run | 31 | 0 |
| number-trace | 10 | 0 |
| data-diff | 15 | 0 |
| data-clean | 17 | 0 |
| stat-compare | 16 | 0 |
| chart-check | 18 | 0 |
| sheet-audit | 13 | 0 |
| notebook-check | 15 | 0 |
| query-review | 22 | 0 |

`python3 tools/validate.py --strict`: all 11 `data/` skills `ok`.

## Faults the tests caught (fixed before the last run)

- **data-profile**: ISO dates (`2026-02-01`) matched the phone-number pattern, so a date column was reported as personal data. Personal-value patterns now apply to text columns only.
- **number-trace**: the minutes of a time (`10:30`) were read as a report number. A number after `:` is no longer read.
- **sql-run**: `SELECT ... FROM pragma_table_info(...)` is denied by the read-only authorizer. That is the intended behaviour; the test first expected it to run and now expects the denial.
- Four test expectations were wrong about wording (the first statement only is scanned for keywords; aliases are reported by table name; a GROUP BY over a covered index is a warning, not a failure). The tests were corrected to the script's actual, intended behaviour.

## Per skill: tested, and not tested

**data-profile.** Tested: CSV (comma and tab), JSON-lines, SQLite table, latin-1 file, ragged rows, header only, empty file, missing file, .xlsx refused, row cap (not verified), duplicate rows, mixed types with row numbers, N/A words, padded values, identifier with repeats, personal-data hiding and `--show-personal`, `--json` and refusal to overwrite, input unchanged. Not tested: files over the row cap at real size, JSON array input, semicolon CSVs, memory use on large files.

**data-check.** Tested: every rule type failing with the right row numbers, the same rules passing on good data, soft rules, four kinds of rule that cannot run, zero rows failing and allowed, quarantine file and refusal to overwrite, bad and empty rules files, a SQLite dataset with a foreign key into another table, text range on ISO dates. Not tested: very large reference sets, JSON-lines datasets with the checker.

**sql-run.** Tested on SQLite: SELECT, WITH, trailing semicolon, write words inside strings and comments, `replace()`, zero rows, row cap, DELETE, UPDATE after a comment, PRAGMA, two statements, a write inside WITH, unclosed quote, missing table, the time limit interrupting an endless recursive query, the table-valued pragma denial, `--file`, `--log` (no rows logged), database byte-identical after all cases. Other dialects: checked and printed only, LIMIT added or kept, SELECT INTO refused, SQL Server told to add TOP. Not tested: any real Postgres, MySQL or other server (the script never connects); user-defined functions with side effects (the text check cannot see them; the read-only connection is the guard).

**number-trace.** Tested: count, mean with a filter, share, SQL on SQLite, a mismatch, a number with no source, a source that cannot be re-run, ignored years, numbers in code blocks, list numbers, dates and times not read, a stale sources entry, a refused write query (data unchanged), missing data file, report with no numbers, broken JSON. Not tested: numbers written in words, numbers in other locales (`1.204,5`), sum/median/min/max/distinct aggregates individually (sum only).

**data-diff.** Tested: added, removed and changed rows with reordered rows and columns, totals check, `--changes-ok`, `--ignore`, no key (candidates listed), missing key, repeating key, two-column key, CSV against SQLite with and without `--loose`, `--json`, keys `007` and `7` kept apart, inputs unchanged. Not tested: files of more than a few thousand rows.

**data-clean.** Tested: all six operations in one plan, the log replay proof, row count, cleaned values, removed-rows file, input byte-identical, refusal to overwrite, fill with no value refused (no files written), ambiguous and unreadable dates left as they were and reported, parse_date without formats, unknown operation, unknown column, nothing to change, JSON-lines and ragged input refused. Not tested: very wide files, non-UTF-8 input.

**stat-compare.** Tested: a real difference, the same output on a second run (fixed seed), claims supported and not supported, independence unchecked without `--unit`, no difference (not called "equal"), a group too small (no test run), the exact permutation p-value for complete separation (2/12870), repeated units, a unit in both groups, skew and unequal spread warnings, unusable values left out, three groups. Not tested: agreement with an outside statistics package (none installed); the bootstrap interval's coverage.

**chart-check.** Tested: a correct bar chart against its CSV, truncated axis with the apparent and real ratio, a wrong value, no source, missing source file, missing labels and unit, no axis minimum, clipped data, months out of order, a line chart allowed above zero, short series, unsorted unordered bars, a pie with seven slices, eight series and two axes, sum over raw rows, several rows with no aggregate, broken spec, unknown type. Not tested: any rendered image (the script reads specs only); scatter charts beyond parsing.

**sheet-audit.** Tested on workbooks written by the test itself: a sound workbook, error cells, a number typed in a column of formulas (plain and shared formulas), a formula that breaks its row and its column, references to empty cells on the same and another sheet, an external workbook reference, a typed constant in a formula, a hidden sheet, `--sheet`, a formula with no saved result, macros, pivot tables, external links, named ranges, table and whole-column references (all listed as not read), old .xls, CSV, a zip that is not a workbook, missing file, workbook unchanged. Not tested: workbooks saved by Excel, LibreOffice or Google Sheets (only hand-built XML was available); very large workbooks.

**notebook-check.** Tested: a tidy notebook with magics and shell lines, out-of-order cells, never-run cells, error outputs, a name used above its definition, a name defined nowhere, a home-folder path, credentials in a cell and in an output (values not printed), cleared counts, gaps in counts, a cell that does not parse, a star import, non-JSON file, old format, no code cells. Jupyter is **not installed** on this machine, so the "not verified: not re-run" path was tested for real. The re-run path was tested only against a stub program named `jupyter` that copies the file or fails on request: that proves the command line, the refusal to overwrite and the reading of the copy, **not** that real `jupyter nbconvert --execute` works with these arguments. Not run: any real kernel.

**query-review.** Tested on SQLite with 20,000 orders: indexed lookup, full scan of a large table, the large-table line moved, alias traced to its table, JOIN with no ON, comma join with and without a link, a function-wrapped filter, aggregate without LIMIT, leading wildcard, NOT IN subquery, automatic index, CROSS JOIN, a join inside a subquery, production purpose, no database, Postgres and MySQL text-only, non-SELECT refused, missing table, not a SQLite file, `--file`, database byte-identical. Not tested: plans from any other engine; the text checks on very long or generated SQL.

## Not run at all

- Trigger, silence and benefit tests (`tests/<skill>.json`): written, **not run**. `claude plugin eval` and `tools/build_map.py` were not run by instruction (shared files, paid usage).
- `claude plugin validate`: not run.
- No `results.json` exists for this pack, so every skill shows as "not tested" until the evals run.

## Notes on names and scope

- `migration-review` from the study note was not built: schema migrations belong to `migration-check` in the ops pack, which the descriptions name.
- `notebook-check` in docs/SKILLS.md says "run a notebook top to bottom"; this build checks the file and re-runs only with Jupyter present and `--run` given, after asking.
- All thresholds in `references/limits.json` are mstack defaults marked `"verified": false`; the scripts print that.
- The scripts share three blocks of code (report, table loader, read-only SQL guard), copied into each script so that no skill depends on another skill's files. A change to one block has to be made in every script that holds it.

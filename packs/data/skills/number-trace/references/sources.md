# Which numbers trace.py reads out of a report

Read: every number in running text and tables, with thousands commas (`1,204`), decimals (`38.5`) and a trailing `%`.

Not read:
- text inside fenced code blocks and inline `code`;
- web addresses;
- list and heading numbers at the start of a line (`1.`, `2)`);
- numbers glued to letters, slashes or hyphens (`v2`, `Q3`, `2026-11-01`, `3/4`);
- parts of a time (`10:30`).

Years and other numbers that are not data are listed in the sources file under `"ignore"`. A number in the report that is neither ignored nor in `"numbers"` fails the check as "no source".

A number matches when the re-run value, rounded to the decimals shown in the report, equals it. `25.50` must be within 0.005; `26` within 0.5. A percentage is compared in percent: `share` gives percent already; for a SQL fraction add `"scale": 100`.

The same value written twice is one number; every line it appears on is listed. Two different meanings with the same value cannot be told apart by this script; give one of them a different spelling in the sources (for example `12.0` beside `12`), or check them by hand and say so.

Sources that cannot be re-run here (a PDF, a dashboard, a person) are allowed: they keep the number out of "no source", but the run ends as not verified until someone checks them.

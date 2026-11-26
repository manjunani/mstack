---
name: number-trace
description: Ties every number in a report to the query or file aggregate that produced it, re-runs each one, and lists numbers that match, do not match, or have no source. Use when a report, memo, slide text or README quotes figures and someone asks "where does this number come from", "are these numbers still right", or before sending a report with data in it. Not for checking quotes and claims against saved web sources (use cite-check) or for checking a chart's drawing (use chart-check).
license: MIT
metadata:
  pack: data
  version: 0.3.0
  needs: python3
---

# Number trace

Produces a line for every number in a report: matches its re-run source, does not match, has no source, or cannot be re-run here.

## Done when

- A sources file maps each data number in the report to a query or aggregate, or to a stated outside source.
- `scripts/trace.py` ran; every number it read appears in one of its lists.
- Numbers that do not match or have no source are named with their line in the report.

End in exactly one state: **pass** (every number traced and reproduced), **fail** (a mismatch or an untraced number), **not verified** (a source could not be re-run here), or **blocked** (unreadable report or sources file).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| The report and the data it was made from | the paths exist | ask; end as blocked |

## Steps

The script is `scripts/trace.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/trace.py"`.

1. **Check needs.**
2. **Write the sources file**, or read the one that exists. For each number in the report: `value` as written, a `label`, `data`, and either `sql` (a SELECT on a SQLite file; the first cell is the number) or `aggregate` (`count`, `sum`, `mean`, `median`, `min`, `max`, `distinct`, `share`) with `column` and `where`. A number from a PDF or a person gets a `note` and no query. Years and dates that are not data go under `ignore`. Format and what is read: `references/sources.md`. Take each source from where the author got it; do not search for a query that happens to give the right number.
3. **Run.**
   ```
   python3 scripts/trace.py <report.md> <sources.json>
   ```
4. **Read the result.** A mismatch means the report, the data or the query changed: say which is known, do not pick one. "No source" means nobody can say where the number came from.
5. **Report.** End state first. Then mismatches with both values, untraced numbers with their lines, numbers that could not be re-run, then the count that matched.

## Rules

- Never edit the report's numbers to make them match. Report the difference; the author decides.
- Never mark a number as ignored to clear a "no source" line unless it is not data (a year, a version, a page number).
- SQL sources run through the same read-only guard as `sql-run`; a query that writes is refused.
- The same value with two meanings is one entry; say so when that happens.

## Not for

- Checking quotes and claims against web sources → use `cite-check`.
- Whether a chart draws its numbers honestly → use `chart-check`.
- Measuring the cost of an AI flow → use `spend-check`.

## Level

- beginner: explain the four outcomes and how to write one sources entry.
- standard: as written.
- expert: the mismatches, the untraced numbers and the RESULT line. Every number still re-runs.

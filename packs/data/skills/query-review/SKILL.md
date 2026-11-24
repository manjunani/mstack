---
name: query-review
description: Reviews one SQL query without running it: SELECT *, a join missing its condition, WHERE date(created_at) or other functions that stop an index being used, no LIMIT, and on SQLite the query plan's full scans. Use when asked "is this SQL ok", to review a query before a dashboard or release, whether a query uses an index, or what is risky or slow in a postgres, MySQL or SQLite query. Start it even before the query is pasted; it asks for the query. Not for getting the results (use sql-run) or migrations that add indexes (use migration-check).
license: MIT
metadata:
  pack: data
  version: 0.2.1
  needs: python3
---

# Query review

Produces findings on one query's text and, for SQLite, on its real plan, with each finding tied to a plan line or a piece of the statement.

## Done when

- `scripts/review.py` ran on the exact statement and its RESULT line is in the reply.
- For SQLite the plan was read from the database; for other engines the reply says the plan was not read and asks for the engine's own EXPLAIN output.
- Any rewrite offered comes with the plan before and after, or is marked not verified.

End in exactly one state: **pass** (no blocking finding and the plan was read), **fail** (a join with no condition, or a full scan of a large table), **not verified** (no plan was read), or **blocked** (not a single SELECT or WITH, or not a SQLite file).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| For the plan: the SQLite file | the path exists | text checks only; not verified |

## Steps

The script is `scripts/review.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/review.py"`.

1. **Check needs.** Get the exact statement, not a paraphrase.
2. **Review.**
   ```
   python3 scripts/review.py --file query.sql --db data.sqlite [--purpose production] [--large-rows 10000]
   python3 scripts/review.py --sql "<statement>" --dialect postgres
   ```
   Only EXPLAIN QUERY PLAN and a row count per scanned table run, read-only, with a time limit. `--purpose production` stops asking for a LIMIT on queries meant to return everything.
3. **For other engines**, ask the user to run `EXPLAIN` (Postgres: `EXPLAIN (ANALYZE, BUFFERS)` on a copy, not production) and read it beside the text findings.
4. **If proposing a fix** (an index, a rewrite), run the review again on the new version, on a copy of the database where an index was added, and show both plans.
5. **Report.** End state first. Then blocking findings, warnings with the plan lines, what was not checked.

## Rules

- Never create an index or change the schema in the user's database from this skill. Index changes are migrations: `migration-check`.
- A plan on a small test copy can differ from production. Say which data the plan came from.
- The large-table line is in `references/limits.json` and is an unverified default.

## Not for

- Getting the query's rows → use `sql-run`.
- Reviewing a schema migration → use `migration-check`.
- Watching what queries cost on a cloud bill → use `cost-watch`.

## Level

- beginner: explain each plan line the findings point at.
- standard: as written.
- expert: findings and the RESULT line. Every check still runs.

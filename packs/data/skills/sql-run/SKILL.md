---
name: sql-run
description: Runs one SQL query read-only with the limits inside the runner, with a single SELECT or WITH only, the SQLite file opened read-only, a row cap, a time limit, the query plan printed with the rows. Use when the user wants an answer pulled from a database, says "run this query", "how many orders last month", or asks to look at a SQLite file. For Postgres, MySQL and others it only checks the statement and hands it over. Not for judging a query's plan and risks (use query-review) or changing data.
license: MIT
metadata:
  pack: data
  version: 0.1.0
  needs: python3
---

# SQL run

Produces rows from one read-only statement, with the plan, the row count, whether the cap cut it short, and a result hash.

## Done when

- The statement went through `scripts/run.py`, not through a client typed by hand.
- The reply gives the rows (or the part needed), the row count and whether more rows exist than were fetched.
- For a non-SQLite database: the checked statement is handed over, and the reply says it was not run here.

End in exactly one state: **pass** (ran inside the limits), **fail** (refused as not read-only, stopped at the time limit, or rejected by the database), **not verified** (another dialect: checked, not run), or **blocked** (no database file, or not a SQLite file).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| For SQLite: the file | the path exists | ask for it; end as blocked |
| For other engines: the user's own client and a read-only role | the user says which | hand the statement over; do not connect |

## Steps

The script is `scripts/run.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/run.py"`.

1. **Check needs.** Learn the tables first when unsure: `SELECT name, sql FROM sqlite_master` through the same script.
2. **Write one statement** that answers the question. Name the columns.
3. **Run.**
   ```
   python3 scripts/run.py --db <file.sqlite> --sql "<statement>" [--limit 200] [--timeout 5] [--log .mstack/sql-runs.jsonl]
   python3 scripts/run.py --dialect postgres --file query.sql
   ```
   Defaults for the cap and the time limit are in `references/limits.json`.
4. **Read the output.** If the cap was hit, totals computed from the shown rows are partial: aggregate in SQL instead. Zero rows is a result to question (filter, date format, case) before it is an answer.
5. **Report.** End state first. Then the answer, the statement, the row count and truncation, and anything not verified.

## Rules

- The script's text check can be fooled; the real guard is the read-only connection (SQLite) or a role that cannot write (other engines). Say this when the user asks how safe it is.
- Never work around a refusal by rewording a write as a read, or by opening the database another way.
- Never connect to a production database from this skill. For other engines the user runs the statement.
- A row cap bounds rows returned, not rows scanned. For a slow or large query, run `query-review` first.
- No passwords in commands, files or logs.

## Not for

- Judging whether a query is slow or risky → use `query-review`.
- Checking a dataset against rules → use `data-check`.
- Changing schema or data → use `migration-check` for schema changes; writes are out of scope here.

## Level

- beginner: explain the plan lines and why the row cap exists.
- standard: as written.
- expert: the rows and the RESULT line. The limits stay on at every level.

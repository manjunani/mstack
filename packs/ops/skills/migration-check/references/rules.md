# Rules of sqlrules.py

Checked: 2026-11-22. Verified against a primary source: **no**. The lock behaviour below is PostgreSQL's as it is
commonly described; it was written from memory and not read in a version's manual during this work. Before a rule
decides a release, confirm it in the manual for the engine version in use.

| Rule | Level | Fires on | Why | Safer form |
|---|---|---|---|---|
| `drop-table` | BLOCK | `DROP TABLE` | Rows are gone | Drop in a later migration, after a restore was proven |
| `drop-column` | BLOCK | `ALTER TABLE .. DROP [COLUMN]` | The column's data is gone; a down step recreates the column empty | Stop using it in code, deploy, then drop later |
| `truncate` | BLOCK | `TRUNCATE` | Every row removed | Confirm with the user; prove a restore first |
| `delete-all` | BLOCK | `DELETE FROM` with no `WHERE` | Every row removed | Add the condition |
| `type-change` | BLOCK | `ALTER COLUMN .. TYPE`, `MODIFY`, `CHANGE` | Table rewrite under a lock; narrowing loses data | New column, copy in batches, switch, drop |
| `rename` | BLOCK | `RENAME COLUMN`, `RENAME TO`, `RENAME TABLE` | Running code still uses the old name | Add new, write both, move readers, remove old |
| `not-null-no-default` | BLOCK | `ADD COLUMN .. NOT NULL` with no `DEFAULT` | Fails on a table with rows | Add with a default, or nullable then fill |
| `index-blocks-writes` | BLOCK | `CREATE INDEX` without `CONCURRENTLY` on an existing table | Writes wait until the index is built | `CREATE INDEX CONCURRENTLY` |
| `concurrent-in-transaction` | BLOCK | `CREATE INDEX CONCURRENTLY` between `BEGIN` and `COMMIT` | Not allowed in a transaction block | Own migration, no wrapping transaction |
| `no-way-back` | BLOCK | No down file and no down marker | No tested way to undo | Write it, or declare forward-only |
| `set-not-null` | WARN | `ALTER COLUMN .. SET NOT NULL` | Reads the whole table under a lock | Validated check constraint first |
| `constraint-validates` | WARN | `ADD .. FOREIGN KEY` or `CHECK` without `NOT VALID` | Validates every row under a lock | `NOT VALID`, then `VALIDATE CONSTRAINT` |
| `update-all` | WARN | `UPDATE` with no `WHERE` | Rewrites every row in one transaction | Batches |
| `schema-and-data` | WARN | Schema and data statements in one file | One long transaction holds the schema lock | Separate files |

## What the script cannot see

- Table size. A plain index build on a table with a hundred rows is harmless; the script cannot know the size.
- A transaction that the migration tool wraps around each file. `concurrent-in-transaction` sees only `BEGIN` written in the file.
- Statements built at run time by a migration written in another language. Check the SQL the tool prints.
- Whether the SQL is valid. Only applying it to a scratch database proves that.
- Old names used through string building in code. The `--code` search finds whole words only.

## Where a way back is looked for

`X.up.sql` with `X.down.sql`; `up.sql` with `down.sql` in the same folder; `X.sql` with `X.down.sql`, `X.undo.sql` or
`X_down.sql`; `V1__x.sql` with `U1__x.sql`; or a comment line inside the file that starts with `-- +goose Down`,
`-- +migrate Down`, `-- migrate:down`, `-- down`, `-- rollback` or `-- undo` and has at least one statement after it.

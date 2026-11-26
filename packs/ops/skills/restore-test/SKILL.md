---
name: restore-test
description: Restores a backup into a new scratch folder and proves the data is in it, by an integrity check and row or file counts compared with numbers the user states. Use when the user asks "do our backups work?" or "can we restore from this dump?", a backup was just taken, or a risky change is about to rely on one. Not for removing files with an undo (use safe-delete) or for reviewing the SQL of a schema change (use migration-check).
license: MIT
metadata:
  pack: ops
  version: 0.3.0
  needs: python3
---

# Restore test

Produces a restored copy in a scratch folder and a report: did it restore, is it intact, do the counts match what the user expects.

## Done when

- The backup was restored into a folder that did not exist before the run. The backup file itself was only read.
- The integrity check passed and each expected count or path was compared with what the copy holds.
- The reply states where the scratch copy is and that it holds real data.

End in exactly one state: **pass**, **fail** (which check, expected against found), **not verified** (restored but no expected counts were stated, or the engine is one the script cannot restore), or **blocked** (no backup file, or no yes from the user to fetch one).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| A backup as a local file | the user names the file | see step 2. If no backup exists at all, report that as the finding; end as blocked |
| Expected numbers | the user states rows per key table, or files and paths | ask; without them the result can only be not verified |

## Steps

The script is `scripts/restore.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/restore.py"`.

1. **Check needs.** Ask what the backup is (a SQLite file, a SQL dump, an archive of a folder, or another database's dump) and when it was taken.
2. **Ask before any fetch.** If the backup is on a host, do not download it on your own. Say that it is a copy of real data, how large it is if known, that the transfer may cost money, and where it will be stored. Wait for a yes, or let the user fetch it. Never write a database password or token into a command.
3. **Ask for the expected numbers** from a source other than the backup: the live system's own counts, a dashboard, the user's knowledge. A count read from the backup and compared with itself proves nothing.
4. **Restore and check.**
   ```
   python3 scripts/restore.py sqlite backups/app-2026-11-21.sqlite --expect users=1200 --expect "orders>=5000" --newest orders.created_at
   python3 scripts/restore.py archive backups/uploads.tar.gz --expect-files ">=340" --expect-path uploads/avatars
   ```
   `--tolerance 2` accepts counts within 2 percent, for a live system that kept changing after the backup. `--manifest sums.txt` checks sha256 sums.
5. **Other databases.** The script cannot restore PostgreSQL, MySQL or MongoDB dumps. Print the steps:
   ```
   python3 scripts/restore.py checklist --engine postgres
   ```
   That run ends as not verified. The user runs the steps on a scratch database, never on a live one, and saves the count output to a file. Then:
   ```
   python3 scripts/restore.py checklist --engine postgres --evidence counts.txt --scratch-name restore_test_20261122 --expect users=1200
   ```
   Say in the report that the counts come from output the user supplied.
6. **Read the output**: restore time, rows per table, the newest record against the backup time, each expectation.
7. **Report.** End state first, then what was restored where, each expectation with expected and found, how old the newest record is, and what is not verified. Do not delete the scratch copy; name `safe-delete` for that.

## Rules

- Never restore into, or run a restore tool against, a database that anything uses. The script writes only to a new folder under `.mstack/restore-test/`; for other engines the scratch database is created by the user.
- A backup counts as proven only after this test passed on it. "The file exists" and "the dump command exited 0" are not proof.
- A failed restore is the result, not an obstacle. Report it; do not repair the backup file.
- Do not print rows from the restored data. Counts and the newest timestamp are enough.
- Tool names in the checklist are unverified and say so; read each tool's own help.

## Not for

- Removing files so the removal can be undone → use `safe-delete`.
- Checking a migration's SQL before it runs → use `migration-check`.
- Returning a service to its previous version → use `rollback`.

## Level

- beginner: explain why an untested backup is a risk, and what an integrity check does and does not prove.
- standard: as written.
- expert: the script's lines and the end state. Steps 2 and 3 are asked at every level.

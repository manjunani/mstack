---
name: data-diff
description: Compares two versions of a dataset by key and reports rows added, removed and changed, which columns changed and how often, with before and after values; reordered rows and columns are not counted as changes, and the totals are checked to add up. Use when asking "what changed between yesterday's export and today's", after a pipeline or cleaning run, or to prove a refactor left the output the same. Not for a first look at one file (use data-profile) or for code diffs (use git).
license: MIT
metadata:
  pack: data
  version: 0.2.1
  needs: python3
---

# Data diff

Produces counts of added, removed, changed and unchanged rows, changes per column, a sample of changed values, and a check that the counts add up.

## Done when

- `scripts/diff.py` ran with a key that identifies rows in both versions.
- The totals line holds: removed + changed + unchanged = old rows, added + changed + unchanged = new rows.
- The reply says whether the difference was expected (`--changes-ok`) or is a finding.

End in exactly one state: **pass** (no difference, or expected differences listed), **fail** (the versions differ, or a file is broken), **not verified** (columns left out with `--ignore` are named as unchecked), or **blocked** (no key, a key that repeats, an unreadable file).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| Both versions | the paths exist | ask; end as blocked |
| A key | the user or the schema names it | run without `--key`: the script lists candidate columns, then ask |

## Steps

The script is `scripts/diff.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/diff.py"`.

1. **Check needs.**
2. **Find the key.** Run once without `--key`; it stops and lists columns unique in both files. A unique column is not always the right key (a row number is unique and meaningless). Confirm with the user.
3. **Diff.**
   ```
   python3 scripts/diff.py <old> <new> --key id [--loose] [--ignore updated_at] [--changes-ok] [--json NEW_FILE]
   ```
   `--loose` compares numbers by value (1 equals 1.0) and trims spaces; use it between a CSV and a database, and say that it was used. `--ignore` is for columns expected to change (timestamps); they are listed as not checked.
4. **Report.** End state first. Then the row counts, the totals line, columns added or removed, changes per column, and a few before and after values.

## Rules

- A key that repeats or is empty blocks the diff. Do not drop the bad rows to make it work; report them.
- Show a sample of changed values, not whole rows, when the data may hold personal details.
- A diff only reads. It never writes to either version.

## Not for

- Describing one file → use `data-profile`.
- Checking rows against rules → use `data-check`.
- Comparing code or text files → use git.

## Level

- beginner: explain what the key does and why the totals must add up.
- standard: as written.
- expert: counts, changes per column and the RESULT line. The totals check runs at every level.

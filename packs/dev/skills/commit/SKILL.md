---
name: commit
description: Turns a mixed working tree into clean commits, one per reason for change. Scans the staged lines for secrets and conflict markers with redacted output, lints each message and warns on the default branch. Use when the user says commit this, commit my changes, split this into commits, or write the commit message. Not for finishing a branch with a merge or a pull request (use land) or for cutting a version (use release).
license: MIT
metadata:
  pack: dev
  version: 0.2.1
  needs: python3, git
---

# Commit

Produces one or more local commits, each holding only the files meant for it, each passing the secret scan and the message lint.

## Done when

- `gate.py check` exited 0 right before each commit.
- `gate.py last --files ...` exited 0 right after each commit: the commit holds exactly the files meant for it.
- Files held back (secret files, generated output, unrelated work) are named in the report.

End in exactly one state: **pass**, **fail** (a secret, a conflict marker or a message problem; show the redacted line), **not verified** (nothing was staged, so nothing was scanned), or **blocked** (the user has to decide: committing on the default branch, a file that may be a secret, how to split).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| git | `git rev-parse --is-inside-work-tree` | end as blocked |

## Steps

The script is `scripts/gate.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/gate.py"`.

1. **See the tree.**
   ```
   python3 scripts/gate.py tree
   python3 scripts/gate.py branch
   ```
   On the default branch: ask whether to commit there or on a new branch (`git switch -c <name>` keeps the changes). Do not decide alone.
2. **Plan the groups.** The script's groups are a start. One commit per reason for change: a fix and its test together; a rename apart from a behaviour change; dependency files with the change that needed them. Leave `HOLD BACK` files out unless the user says otherwise. Show the groups and continue unless the user objects.
3. **Stage one group, naming every file.** `git add <file> <file>`; for part of a file, `git add -p <file>`. Never `git add -A`, `git add .` or `git commit -a`.
4. **Write the message** in the repository's style (`git log -10 --format=%s`): a subject that names what changed, a blank line, then why, when the change is not obvious.
5. **Gate.**
   ```
   python3 scripts/gate.py check -m "<message>"          # or --file <message file>
   ```
   - A secret: unstage the file (`git restore --staged <file>`), move the value to the environment or the user's secret store, and tell the user. If the value was ever committed or pushed, say that it has to be rotated; removing it from a later commit does not hide it.
   - A false alarm: add a waiver with a real reason to `.mstack/commit-waivers.json` only after the user agreed.
   - A conflict marker: the merge is not finished. Stop and show it.
6. **Commit and confirm.**
   ```
   git commit -m "<message>"
   python3 scripts/gate.py last --files <the files of this group>
   ```
   If `last` fails, the commit is still local: `git reset --soft HEAD~1`, fix the group, commit again.
7. **Repeat** steps 3 to 6 for each group.
8. **Report.** End state first, then each commit (short id and subject), the files held back and why, and any warning that was not acted on.

## Rules

- Commits stay local. Pushing is the job of `land` and needs the user's word.
- Never skip the repository's own hooks (`--no-verify`) and never rewrite commits that were already pushed.
- The scan only reads staged lines. A secret in an unstaged file is not committed, and it is not checked either: say so if the user asks.
- The token shapes are from memory and not verified; a clean scan lowers the risk, it does not prove there is no secret.
- Do not stage files the user did not create or change in this work without asking.

## Not for

- Merging the branch, pushing or opening a pull request → use `land`.
- Tagging a version with notes → use `release`.
- Proving the tests pass before committing → use `verify`; if it is not installed, run the project's test command and show its output.
- A security review of the code → use `secure`.

## Level

- beginner: explain why each group is separate, and show the exact `git add` before running it.
- standard: as written.
- expert: show the groups and the commit list only. The scan, the lint and the `last` check run at every level.

---
name: release
description: Cuts a version from the exact range since the last tag: lists the commits, migrations, config and dependency changes in it, drafts release notes, and refuses to go on until a rollback step is written in the release file. Use when the user says cut a release, tag a version, bump to 1.4.0, write release notes or a changelog for what shipped. Not for finishing one branch (use land) or for checks after a deploy (use deploy-check).
license: MIT
metadata:
  pack: dev
  version: 0.1.0
  needs: python3, git
---

# Release

Produces a release file with notes for one exact commit range, a written way back to the previous version, and, on the user's word, an annotated tag.

## Done when

- `cut.py range` printed the range as full commit ids.
- `cut.py ready <version>` exited 0: the rollback section holds a real step (and says what happens to the database when the range has migrations), the range has not moved, the tag does not exist, the tree is clean.
- The tag exists only if the user said yes to the tag command.

End in exactly one state: **pass**, **fail** (no rollback, range moved, tag exists, dirty tree; show the lines), **not verified** (the version bump in project files or the notes could not be checked; say which), or **blocked** (nothing to release, or the user must pick the version or write the rollback).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3, git | `python3 --version`, `git rev-parse HEAD` | end as blocked |
| The version number | the user names it, or the project's own convention | propose one from the commits (fixes only: patch; features: minor; breaking: major) and ask |

## Steps

The script is `scripts/cut.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/cut.py"`.

1. **Fix the range.**
   ```
   python3 scripts/cut.py range            # --since <tag or commit> to start elsewhere
   ```
   Read every risky file it lists: a migration, an environment or a config change usually needs a step in the release or in the rollback.
2. **Run the checks** on the commit to be tagged: use `verify` if installed, otherwise the project's full test command. A red suite ends here as fail.
3. **Draft.**
   ```
   python3 scripts/cut.py draft <version>
   ```
   It writes `.mstack/release/<version>.md` and never overwrites one.
4. **Rewrite the notes for users**: what they can now do, what changed for them, what they must do (a new setting, a migration to run). Drop internal commits. Do not describe a change that is not in the range.
5. **Write the rollback.** Exact steps to return to the previous version: which command or button, what happens to data this version writes, which migration to reverse first, who can do it. If nobody knows, ask the user; do not invent a procedure.
6. **Bump the version** in the project's own files if it keeps one (`package.json`, `pyproject.toml`, `Cargo.toml`, a `VERSION` file) and commit that with `commit`, or as one commit naming only those files.
7. **Check.**
   ```
   python3 scripts/cut.py ready <version>
   ```
8. **Ask, then tag.** Show the tag command the script printed and the notes. Only on a yes run it. Pushing the tag (`git push origin <tag>`) and publishing a release page are separate questions.
9. **Report.** End state first, then the version, the range, the risky files and how the notes and rollback deal with each, and whether the tag was made and pushed.

## Rules

- Notes come from the range, never from memory of what was planned.
- A release with migrations and no database step in its rollback is not ready, whatever the urgency.
- Never move or delete an existing tag. A wrong tag that was pushed gets a new version.
- The script never tags, pushes or publishes; those happen only on the user's word.

## Not for

- Finishing a branch (merge or pull request) → use `land`.
- Checking a running service after deploying → use `deploy-check`.
- Reviewing a migration in depth → use `migration-check`; without it, read the migration and its down step yourself.
- Committing the changes first → use `commit`.

## Level

- beginner: explain the range, why a rollback is needed and what a tag is before asking.
- standard: as written.
- expert: range, risky files and the ready result. The rollback check is never skipped.

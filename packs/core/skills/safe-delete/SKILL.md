---
name: safe-delete
description: Deletes files and folders so the removal can be undone: lists what would go, what refers to it and what git cannot bring back, then moves it to a trash folder with an undo command. Use when asked to delete, remove, clean up, clear out, wipe, nuke or get rid of files, folders, unused components, old code or build output, or to free up space. Not for lines inside a file such as imports or logs, for reverting a code change (use git) or for finishing a branch (use land).
license: MIT
metadata:
  pack: core
  version: 0.3.0
  needs: python3, git
---

# Safe delete

Produces a manifest of what was removed, a trash copy that was checked, and one command that puts everything back.

## Done when

- The user saw the manifest (targets, file counts, sizes, what refers to them, what exists only here) and said yes to that manifest.
- The script moved the targets to the trash and confirmed each copy is complete.
- The undo command is in the reply.
- The project still works: run `verify`.

End in exactly one state: **pass**, **fail**, **not verified** (say which check did not run), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| git | `git rev-parse --is-inside-work-tree` | carry on; the manifest will say that nothing can be restored from history |

## Steps

The script is `scripts/manifest.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/manifest.py"`.

1. **Name the real targets.** Expand every pattern and every vague phrase ("old stuff", "the unused ones") into actual paths, and read the list before going on.
2. **Plan.** This removes nothing.
   ```
   python3 scripts/manifest.py plan <path> [<path> ...] --reason "<why>"
   ```
3. **Read the manifest.** Three things matter:
   - *Referred to by*: files that mention the target. Open them. If they still need it, stop.
   - *Exists only here*: files git cannot bring back (untracked, ignored, uncommitted). These are the real risk.
   - A count or size much larger than expected. Stop and ask.
4. **Ask.** Show the manifest to the user in full sentences: what goes, how much, what depends on it, and that it can be undone. Wait for a yes to this manifest. An earlier or general "go ahead" does not count.
5. **Apply.**
   ```
   python3 scripts/manifest.py apply <id>
   ```
   The script refuses if a target changed since the plan. Plan again and ask again.
6. **Check the project.** Run `verify`. If something broke, run `python3 scripts/manifest.py undo <id>` and report.
7. **Report.** End state first, then the manifest id, where the copy is, the undo command, and that the copy still uses disk space until the user asks to purge it.

`purge` deletes the trash copy for good. Run it only when the user asks for that, by manifest id.

## Rules

- Never remove with `rm -r`, `git clean`, `find -delete` or a similar command when this skill can do it. In Claude Code the pack's guard hook blocks those and points here.
- The script handles files inside the project. For anything else, do not improvise: database tables and rows, cloud resources, volumes, remote branches, git history. State what would be lost, find out whether a backup exists outside the thing being removed, and end as blocked until the user decides.
- A backup counts only after something was restored from it.
- Folders that can be rebuilt (`node_modules`, `dist`, caches) still go through `plan`; the manifest marks them, and the user may choose a plain delete for them.
- Where no hook runs (other tools, or `MSTACK_GUARD=off`), these steps are instructions only and nothing enforces them. Say so if the user asks how safe this is.

## Not for

- Undoing a code change → use git (`git revert`, `git restore`).
- Finishing or deleting a branch after work → use `land`.
- Keeping edits inside one folder → use `scope-lock`.

## Level

- beginner: explain each part of the manifest and what "exists only here" means.
- standard: as written.
- expert: show the manifest as printed, ask once. The plan, the question and the copy check are never skipped.

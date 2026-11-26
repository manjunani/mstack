---
name: scope-lock
description: Keeps file edits inside one folder until released, so a task cannot change files elsewhere by accident. Sets a lock that the guard hook enforces on Write and Edit calls. Use when the user says to touch only one folder, to stay out of a part of the code, or to work on one module without changing anything else. Not for removing files (use safe-delete) or for checking a finished change (use review).
license: MIT
metadata:
  pack: core
  version: 0.3.1
  needs: python3
---

# Scope lock

Produces a lock file naming the one folder where edits are allowed, and a log of when it was set and released.

## Done when

- The lock is set and `status` shows the folder the user named.
- One test proves it: a path outside the folder is reported as denied.
- The user knows how to release it.

End in exactly one state: **pass**, **fail**, **not verified** (say which check did not run), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| The guard hook (Claude Code, mstack-core installed) | the pack is installed as a plugin | carry on, and tell the user the lock is then a rule you follow, with nothing enforcing it |

## Steps

The script is `scripts/lock.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/lock.py"`.

1. **Confirm the folder.** One folder, inside the project. If the user named several, ask which one, or lock their common parent and say so.
2. **Set the lock.**
   ```
   python3 scripts/lock.py set <folder> --reason "<the task>"
   ```
3. **Prove it.** Pick a real file outside the folder.
   ```
   python3 scripts/lock.py test <path outside>    # expect: denied, exit 1
   python3 scripts/lock.py test <path inside>     # expect: allowed, exit 0
   ```
4. **Work.** If an edit outside the folder turns out to be needed, stop and tell the user which file and why. Do not release the lock yourself to get past it.
5. **Release** when the user says the task is over, or asks.
   ```
   python3 scripts/lock.py release
   ```
6. **Report.** End state first, then the locked folder, the result of the two tests, and the release command.

## Rules

- Only the user decides to release or widen the lock.
- The lock covers the file-edit tools. It does not parse shell commands, so a script, a formatter or a code generator can still write elsewhere. Say this when you set the lock, and check `git status` for stray changes before finishing.
- `.mstack/` and temporary folders stay writable, so records and scratch work still function.
- The lock stays until released, across sessions. `status` shows whether one is active.

## Not for

- Removing files → use `safe-delete`.
- Reviewing what a change touched → use `review`.
- Splitting work between agents so they do not collide → use `parallel`.

## Level

- beginner: explain what the lock does and does not stop, in two sentences.
- standard: as written.
- expert: set, run both tests, report in three lines. The tests are never skipped.

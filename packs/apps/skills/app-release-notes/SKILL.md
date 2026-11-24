---
name: app-release-notes
description: Drafts "What's New" notes for an app version from the real commits between two tags and checks them: each line names a commit in the range, and each user-facing feat, fix or perf commit appears or is skipped on purpose. Use when the user asks for release notes, a changelog for the App Store or TestFlight, or "what changed since 1.2". Not for cutting the release itself (use release) or for the store listing text (use store-listing-check).
license: MIT
metadata:
  pack: apps
  version: 0.2.2
  needs: python3, git
---

# App release notes

Produces a draft notes file where each line carries the hash of the commit behind it, and a check that ties the two together.

## Done when

- The range is confirmed by the user (the last released tag and the new one, or HEAD).
- `scripts/notescheck.py check <from> <to> <notes>` exits 0.
- The reply gives the draft without the hashes for publishing, and says nothing was published.

End in exactly one state: **pass**, **fail** (lines with no commit, or user-facing commits missing), **not verified** (empty range), or **blocked** (no git, a tag that does not exist).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3, git | `git rev-parse --is-inside-work-tree` | end as blocked |
| Two refs | `git tag --sort=-creatordate` | ask which tag was the last store release; the newest tag is only a guess |

## Steps

The script is `scripts/notescheck.py` (`"${CLAUDE_SKILL_DIR}/scripts/notescheck.py"` in Claude Code).

1. **Confirm the range** with the user.
2. **Collect.** `python3 scripts/notescheck.py collect <from> <to>`. It groups by prefix and lists the files each commit touched. Commit messages are claims; look at the files when a message is vague.
3. **Draft** one line per user-visible change, in plain words a user understands, with the short hash at the end of the line: `- Notes can be pinned to the top [a1b2c3d]`. Several commits may share a line.
4. **Check.**
   ```
   python3 scripts/notescheck.py check <from> <to> <notes.md> [--skip <hash>]
   ```
   `--skip` only for a commit the user agrees to leave out.
5. **Report.** End state, the range, the draft with hashes removed, any skipped commits. Store length limits are the store's own; the store's documentation is the source.

## Rules

- No line without a commit behind it. Do not describe a change the range does not contain.
- Do not publish, upload or tag anything.
- Leave out internal work (ci, chore, refactor) unless it changes what users see.

## Not for

- Tagging, building and shipping → use `release`.
- Store description and keywords → use `store-listing-check`.
- Proving the release works → use `verify`.

## Level

- beginner: explain conventional prefixes and why each line keeps a hash until publishing.
- standard: as written.
- expert: the draft and the RESULT line. The check always runs.

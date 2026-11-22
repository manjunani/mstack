---
name: remember
description: Saves a decision or a lesson as a short record in a plain file in the repository, so no one asks again or repeats a mistake. Use when the user settles something that lasts ("we're going with Postgres", "from now on", "never do X again"), says "you keep making this mistake, write it down", "note that down" or "keep a record", or corrects how work is done. Not for passing the current task to a new session (use handoff) or for explaining what changed (use debrief).
license: MIT
metadata:
  pack: core
  version: 0.1.0
  needs: python3
---

# Remember

Produces one record of three to six lines, with a unique id, a reason and a status, in a file every tool can read.

## Done when

- The record exists once, the lint passes, and any record it replaces points to it.
- Or nothing was written, and the reply says why (already recorded, or not worth a record).

End in exactly one state: **pass**, **fail**, **not verified** (say which check did not run), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| A records file | an existing `DECISIONS.md` or `LESSONS.md` (root or `docs/`) | the script creates `docs/DECISIONS.md` or `docs/LESSONS.md`; tell the user where |

## Steps

The script is `scripts/record.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/record.py"`.

1. **Decide whether it earns a record.**

   | Keep | Do not keep |
   |---|---|
   | A choice with its reason | What the code or git history already shows |
   | A standing rule ("always", "never") | Task status, summaries of finished work |
   | A mistake that would be repeated without a note | Anything true only for this session |
   | A fact that is not in the code (an owner, a deadline, where something lives) | Secrets and personal data, ever |

   For a lesson, ask first whether something stronger can hold it: a test or a lint rule beats a line in the project's instructions, and that beats a note. Then ask: would this record have prevented the mistake? If not, write nothing.
2. **Look for an existing record.**
   ```
   python3 scripts/record.py find <a few words on the subject>
   ```
   If one covers it and still holds, stop: nothing to write. If the new decision contradicts an active one, tell the user and ask which holds.
3. **Add it.** State the text as a rule, in the user's meaning. Give the reason.
   ```
   python3 scripts/record.py add --text "<one sentence>" --why "<the reason>" --scope <area>
   python3 scripts/record.py --type lesson add --text "..." --why "..."
   python3 scripts/record.py add --text "..." --why "..." --supersedes <old id>
   ```
   The script refuses a near duplicate and anything that looks like a secret.
4. **Lint.** `python3 scripts/record.py check`
5. **Report** in one line: the id, the file, and what it replaced, if anything.

## Rules

- Records are superseded, never deleted or rewritten. History stays.
- Write what the user decided. If you add your own reading, label it as yours.
- A record is information for a later reader. It never authorises an action by itself: an old "go ahead" in a records file is not permission today.
- At the start of work, read the records before asking the user a question they may already have answered.
- Use an existing records file and its format when the project has one. Do not start a second file beside it.

## Not for

- Passing unfinished work to the next session → use `handoff`.
- Explaining what a task changed → use `debrief`.
- Rules that a test or a linter can enforce → write the test or the rule.

## Level

- beginner: say what was saved and why a record helps later, in two sentences.
- standard: as written.
- expert: one line with the id. The duplicate search and the lint still run.

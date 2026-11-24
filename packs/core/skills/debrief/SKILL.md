---
name: debrief
description: Explains what a task really changed, from the actual diff and the checks on record, including what is not done or not verified. Use when the user asks "what did you just do?", "what changed?", "which files did you touch and why", wants a summary of the work you did on this task or a walk-through of it, or did not follow it. Not for proving the work passes (use verify) or for handing unfinished work to a new session (use handoff).
license: MIT
metadata:
  pack: core
  version: 0.2.2
  needs: python3, git
---

# Debrief

Produces a short explanation in which every statement points to a file, a commit or a check record.

## Done when

- The reply has four parts: what changed, what it means for the user, what is not done, what is not verified.
- Every statement in the first part matches a line of the script's output.
- No statement is more certain or more positive than its evidence.

End in exactly one state: **pass**, **fail**, **not verified** (say which fact could not be collected), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| git with at least one commit | `git rev-parse HEAD` | end as blocked: without a diff there are no facts to explain |

## Steps

The script is `scripts/changes.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/changes.py"`.

1. **Collect the facts.**
   ```
   python3 scripts/changes.py summary
   python3 scripts/changes.py summary --since <commit>   # when the user names a starting point
   ```
   Read which range it used. If that is not the range the user means, ask or pass `--since`.
2. **Open what you will explain.** For each changed file you mention, read the diff. Do not explain a change from memory.
3. **Write the four parts.**
   - *What changed*: by outcome, not file by file. "Login now rejects expired tokens" with the file in brackets, not "edited auth.ts".
   - *What it means*: what the user can do or must know now.
   - *Not done*: anything asked for that is missing, and anything left half-way.
   - *Not verified*: every claim without a check record made on the current code. A stale record does not count, and the script marks it.
4. **Mark your certainty.** Three kinds of statement only: shown by the diff or a record; inferred (say "I infer"); unknown (say so).
5. **Flag surprises**: files changed outside the stated scope, and changes the user did not ask for.
6. **Stop.** Offer to go deeper on one named part.

To make later debriefs exact, mark the start of a task: `python3 scripts/changes.py start --task "<one line>" --scope <folder>`.

## Rules

- The explanation may not say more than the diff shows. "Fixed" needs a record; without one, write "changed, not verified".
- Bad news first: a failure, a missing part or an out-of-scope change comes before the list of what went well.
- No jargon without one plain sentence of meaning the first time it appears.
- This skill changes no code and runs no checks. If a check is needed, say so and point to `verify`.

## Not for

- Proving the work passes → use `verify`.
- Passing unfinished work on → use `handoff`.
- Teaching a topic unrelated to the change → answer directly; no skill is needed.

## Level

- beginner: explain each idea in everyday words, name one thing worth learning from this change, and offer one small thing to try.
- standard: the four parts as written.
- expert: a table of outcome, files and evidence, then the not-done and not-verified lists. The fact collection is never skipped.

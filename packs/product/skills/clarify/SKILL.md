---
name: clarify
description: Settles what the user wants before anything is built. Asks one question at a time until no point that changes the build rests on a guess, then gets a yes on a six-line statement of intent. Use when a request is vague, the goal or the reason behind it is unclear, or the user says "ask me questions", "grill me" or "what am I missing". Not for writing requirements once the goal is clear (use spec), for producing ideas (use ideate) or for ordering tasks (use plan).
license: MIT
metadata:
  pack: product
  version: 0.2.2
  needs: python3, a user who can answer
---

# Clarify

Produces an intent file: six lines the user said yes to, and a ledger that shows where every point came from.

## Done when

- `scripts/intent.py check` exits 0 on the intent file. That means: every entry carries a provenance label, every user decision names what was turned down and why, nothing that changes the build is assumed or open, and the user's yes was recorded on the content as it is now.
- The user saw the restatement and answered yes in their own words.

End in exactly one state: **pass**, **fail** (the checker's failing lines are shown), **not verified** (say which check did not run), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| A user who can answer | the request came from a person in this conversation | in an unattended run, write the open questions to the intent file and end as blocked; never answer them yourself |

## Steps

The script is `scripts/intent.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/intent.py"`. Intent files live in `.mstack/intent/<short-name>.json`.

1. **Size the request.** If you could already predict the user's answer to anything you would ask, there is nothing to clarify: say so in one line and end as pass. A small, clear change needs no file.
2. **Read before asking.** For each thing you want to know, search the code, the docs and any decision log first. What the project answers becomes a `found in repo` or `found in docs` entry with its path.
3. **Write your guess.**
   ```
   python3 scripts/intent.py template .mstack/intent/<short-name>.json --title "<the work>"
   ```
   Fill the six restatement slots with your current guess. Add one entry per point. Anything you do not know and that would change what gets built is `"status": "open", "changes_build": true`.
4. **Ask one question per message.** Pick the open entry whose answer changes the most. Ask it as an open question first; give your own guess with it, and say what the answer would change. Offer a list of choices only after the user has described the goal in their own words.
5. **Record the answer with its label.**

   | Label | When | Also needed |
   |---|---|---|
   | `user said` | the user stated a fact or a need | |
   | `user chose` | the user picked between alternatives | `rejected`, `reason` |
   | `found in repo`, `found in docs` | you read it | `where` (a path that exists) |
   | `assumed` | your default; allowed only when `changes_build` is false | |

   A bare order ("build it with X") that nobody weighed gets one challenge: name one alternative and what it would cost or save. Then record the user's answer as `user chose` and respect it.
6. **Check, then decide whether to go on.**
   ```
   python3 scripts/intent.py check .mstack/intent/<short-name>.json
   ```
   Go back to step 4 while a `FAIL` line names an open or assumed entry. Stop asking when none is left. If three rounds of answers raised nothing new and entries are still open, say so and end as blocked with the open list.
7. **Get the yes.** Print the restatement and show it to the user, including the assumptions.
   ```
   python3 scripts/intent.py show .mstack/intent/<short-name>.json
   ```
   When the user agrees, record their reply as written. Any later edit to the file voids it.
   ```
   python3 scripts/intent.py confirm .mstack/intent/<short-name>.json --words "<the user's reply>"
   ```
8. **Report.** End state first, then the path of the intent file, the entries by label, and what remains assumed.

## Rules

- Never ask what the project or the conversation already answers.
- One question per message. No question batches, and no menu about tone, format or audience of your own reply.
- Never run `confirm` with words the user did not write, and never mark an entry `user said` from your own inference.
- When the user's word for a thing differs from the word the code uses, settle the term before the next question.
- This skill builds nothing: no code, no spec, no plan. It ends at the confirmed intent.

## Not for

- The goal is clear and needs writing down as checkable lines → use `spec`.
- The user wants ideas or approaches → use `ideate`.
- Choosing between options that are already named → use `compare-options`.
- Finding what could sink a plan that exists → use `premortem`.
- Breaking settled work into tasks → use `plan`.

## Level

- beginner: explain why each question matters and what a label means; show the full ledger before asking for the yes.
- standard: as written.
- expert: shorter questions, no explanation of the labels. The check and the user's confirmation are required at every level.

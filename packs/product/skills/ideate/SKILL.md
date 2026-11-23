---
name: ideate
description: Produces a wide list of options grounded in the project, cuts it with a reason for every cut, and ends with a short list of two or three. Use when the user wants ideas, approaches or alternatives, says "brainstorm", "what are our options" or "how else could we do this", or knows the goal and not the way. Not for scoring options that are already named (use compare-options), for settling what the user wants (use clarify) or for testing a chosen plan (use premortem).
license: MIT
metadata:
  pack: product
  version: 0.2.0
  needs: python3
---

# Ideate

Produces an options file: every candidate that was considered, why each cut one was cut, and two or three survivors with what supports them.

## Done when

- `scripts/options.py freeze` recorded the full list before any option was judged.
- `scripts/options.py check` exits 0: the target count was reached, every rejected option has its own reason, every survivor states its basis, and two or three survive.
- The user has the short list and the list of cuts. No plan and no code were written.

End in exactly one state: **pass**, **fail** (the checker's failing lines are shown), **not verified** (say which check did not run), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| A question to answer | the user's goal can be written as one "how could ..." line | ask for the goal in one sentence; if the goal itself is unclear, use `clarify` if installed, otherwise ask what outcome they want; end as blocked until answered |

## Steps

The script is `scripts/options.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/options.py"`. Options files live in `.mstack/ideas/<short-name>.json`.

1. **Ground first.** Read the parts of the project the question touches, and collect what the user already said about limits and wishes. Each becomes a `grounding` entry: a `where` path with a note, or `"source": "user said"` with a note.
2. **Start the file.** The target is how many distinct candidates to list before judging; 12 unless the user names another number.
   ```
   python3 scripts/options.py template .mstack/ideas/<short-name>.json --question "How could ...?" --target 12
   ```
3. **List without judging.** Split the subject into three to five parts (put them in `axes`) and give each part options. To get past the first obvious ones, take each of these in turn: remove a step; do the opposite; the version with no new code; the version a power user would ask for; how a neighbouring product solves it; what breaks the usual assumption. Include "change nothing". Every option is `"status": "candidate"` with a title and one line on how.
4. **Freeze the list.** This is the proof that the cuts came after the list.
   ```
   python3 scripts/options.py freeze .mstack/ideas/<short-name>.json
   ```
   If it reports too few distinct options, add more; reworded copies count once.
5. **Judge every option** against the grounding. Set `"status": "rejected"` with a `reason` that belongs to that option, or `"status": "survivor"` with a `basis` (and a `where` path when the basis is in the project). Keep two or three.
6. **Check.**
   ```
   python3 scripts/options.py check .mstack/ideas/<short-name>.json
   ```
7. **Report.** End state first. Then the survivors, each with its basis and its main cost. Then the cuts, one line each with the reason, so the user can rescue one. Then stop.

## Rules

- Nothing is judged before the freeze, and nothing frozen is removed or rewritten afterwards. A new thought is a new option.
- A reason names what rules that option out here: a limit the user set, something in the project, a cost. "Not as good" is not a reason.
- A basis is something you read or the user said. An idea you merely like has no basis yet.
- If the user rescues a cut option, change its status, drop another survivor or ask which one goes, and run the check again.
- This skill does not pick the winner and does not plan. It ends with the short list.
- Running several agents in parallel is optional: say first that it multiplies the usage, give each one a different part or a different angle, and merge their options into one file before the freeze.

## Not for

- Choosing between options that already have names → use `compare-options`.
- Working out what the user wants or why → use `clarify`.
- Finding what would make a chosen plan fail → use `premortem`.
- Turning the chosen option into tasks → use `plan`.
- Designing how a screen should look → use `ui-build`.

## Level

- beginner: explain why the list is frozen before judging, and present each survivor with one plain example of how it would work.
- standard: as written.
- expert: survivors and cuts as two short tables, no commentary. The freeze and the check run at every level.

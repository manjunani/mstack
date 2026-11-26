---
name: premortem
description: Assumes a chosen plan has already failed, lists the assumptions it rests on, ranks them by impact and confidence with a script, and names the cheapest test for the worst one, with a pass and a fail line. Use when the user is about to commit to a plan or spec, asks "what could go wrong", "poke holes in this plan" or "what are we betting on". Not for producing alternatives (use ideate), for choosing between options (use compare-options) or for reviewing code (use review).
license: MIT
metadata:
  pack: product
  version: 0.3.0
  needs: python3, a written plan or spec
---

# Premortem

Produces an assumption table sorted by risk, the weakest link named, and a small test for each top risk that says what counts as pass and what counts as fail.

## Done when

- `scripts/assumptions.py rank` exits 0: every top-ranked assumption has a test with what, a cost in time, a pass line and a fail line.
- The ranked table is saved beside the input, and the user has been shown the weakest link and its test.

End in exactly one state: **pass**, **fail** (a top risk has no usable test; the lines are shown), **not verified** (say what could not be checked), or **blocked** (no written plan, or a decision only the user can make).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| A written plan or spec | a file the table can point at | ask the user to write the plan down, or use `spec` if installed; end as blocked |

## Steps

The script is `scripts/assumptions.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/assumptions.py"`. Tables live in `.mstack/premortem/<short-name>.json`.

1. **Read the plan** and what it touches in the project.
2. **Start the table.**
   ```
   python3 scripts/assumptions.py template .mstack/premortem/<short-name>.json --plan <path of the plan>
   ```
3. **Tell the failure story.** It is some months later and the plan failed. Write in `failure` what happened, concretely: who stopped using it, what broke, what it cost.
4. **Find the assumptions behind the story.** For each cause, write what must be true for the plan to work. Look in these places: the people (will they use it, pay, change habit), the technology (does it work at this size), the dependencies (others, services, timing), and the money and time. At least three.
5. **Rate each one.** Impact 1 to 5: how much of the plan is lost if it is wrong. Confidence 1 to 5: how sure, on evidence. Confidence 4 or 5 needs `evidence`; without it the script counts 2. Add `depends_on` where one assumption rests on another, and `reversible: false` where the plan cannot be undone cheaply.
6. **Rank.**
   ```
   python3 scripts/assumptions.py rank .mstack/premortem/<short-name>.json
   ```
7. **Write a test for each top risk.** The smallest thing that would show whether the assumption holds: a conversation, a spike, a measurement, a look at data. Give it a cost in time, a pass line and a fail line, with a number where there is one. Rank again until it passes.
8. **Report.** End state first. Then the weakest link, its test with pass and fail lines, the cheapest test among the top risks, and any top risk that cannot be undone. Ask the user whether to run the test before committing.

## Rules

- Ratings come from evidence or from the user. Say which. A high confidence you cannot back is counted low, and the report says so.
- A test answers one assumption, and its fail line names a result that could really happen. A test that cannot fail is not a test.
- Never soften the failure story to make the plan look safer.
- This skill does not change the plan. If the user wants a new direction after seeing the table, that is `ideate` or `compare-options`.

## Not for

- Producing options or alternatives → use `ideate`.
- Choosing between named options → use `compare-options`.
- Finding defects in code → use `review`.
- Settling what the user wants → use `clarify`.

## Level

- beginner: explain impact, confidence and the risk score with the first row as the example.
- standard: as written.
- expert: the ranked table, the weakest link and its test only. The rank run and the tests for top risks are required at every level.

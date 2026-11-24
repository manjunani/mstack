---
name: compare-options
description: Ranks named options on weighted criteria with a script, applies vetoes, and shows how close the call is and what would flip the winner. Use when the user asks "X or Y", "X vs Y" or "which one", wants a trade-off table for vendors, hosting providers or tools, asks to rank features by reach, effort and how sure we are, or asks "what would have to change for B to win". Not for producing the options (use ideate), testing the chosen plan (use premortem), timing code (use perf-check) or recording the decision (use remember).
license: MIT
metadata:
  pack: product
  version: 0.2.1
  needs: python3
---

# Compare options

Produces a ranked table, the margin of the winner, and the flip points: what would have to be different for another option to win.

## Done when

- `scripts/compare.py rank` ran on a file in which every criterion has a weight from the user and every score has a stated source. The script refuses anything less.
- The reply shows the ranking, the vetoed options, the margin and the flip points as printed, and names every score that rests on an estimate.
- The user made the choice, or was asked to.

End in exactly one state: **pass**, **fail** (first place is tied, or every option is vetoed), **not verified** (say what could not be checked), or **blocked** (say what is needed from the user: a weight, a score's source, a second option).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| Two or more named options | the user named them, or agreed to a list | use `ideate` if installed to produce options; otherwise ask the user to name at least two; end as blocked |
| Weights from the user | the user said how much each criterion counts | ask; never fill one in |

## Steps

The script is `scripts/compare.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/compare.py"`. Comparison files live in `.mstack/compare/<short-name>.json`.

1. **Agree the criteria.** Ask what matters for this decision and what would rule an option out whatever else it offers. The second kind is a veto (`veto_below`).
2. **Get the weights before any score.** Ask the user to spread points across the criteria or to put them in order. Write the weights down first, so they cannot drift toward a favourite.
3. **Start the file.**
   ```
   python3 scripts/compare.py template .mstack/compare/<short-name>.json --decision "<the question>"
   ```
4. **Score each option on each criterion**, on the file's scale. Higher is better on every criterion: for cost, the top score is the cheapest. Each score carries its `source`:

   | Source | Write |
   |---|---|
   | You read it | the file, page or measurement, and the date |
   | The user said it | "user said", with their words |
   | Nobody knows yet | "estimate", and by whom. The script reports it as soft |

5. **Rank.**
   ```
   python3 scripts/compare.py rank .mstack/compare/<short-name>.json
   ```
   Each `REFUSED` line is a question for the user or something to read. Do not fill the gap yourself to make the script run.
6. **Read the flip points.** If one point or less on a single score changes the winner, or the nearest flip sits on a soft score, say that the result rests on that one input, and name the cheapest way to firm it up.
7. **Report.** End state first. Then the table, the winner and margin, the vetoed options with the reason, the two smallest flips in plain words, and the soft scores. Then ask the user to choose.
8. **Offer to record the choice.** If `remember` is installed, offer to save the decision with each rejected option and its reason. Otherwise say that the comparison and its result file stay in `.mstack/compare/`.

## Rules

- Every total, margin and flip point comes from the script. Do no arithmetic by hand, and do not round the script's numbers into a different story.
- Weights are the user's. If a weight changes after the ranking was seen, say so in the report and show both results.
- A veto is a fact about an option that the user treats as disqualifying. It is not a way to remove an option you dislike.
- A score you did not read anywhere is an estimate, and is labelled so. Scores voiced as invented reviewers or personas are estimates too.
- The ranking informs the decision; it is not the decision. A user who picks second place has that right; record their reason.
- A tie is reported as a tie. Do not nudge a score to break it.

## Not for

- There are no options yet → use `ideate`.
- One plan is chosen and needs its risks found → use `premortem`.
- Saving the decision and its reasons → use `remember`.
- The goal itself is unclear → use `clarify`.
- Comparing two versions of code or a diff → use `review`.

## Level

- beginner: explain weights, vetoes and flip points with this decision's own numbers before showing the table.
- standard: as written.
- expert: the table, the flip points and the question "which one?". Weights and sources are asked for at every level.

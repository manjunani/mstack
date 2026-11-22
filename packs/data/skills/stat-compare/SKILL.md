---
name: stat-compare
description: Compares two groups from the raw rows (A/B test, before and after, two segments), giving sizes, means, medians, a seeded permutation test, an interval, an effect size, and warnings on small samples, skew and spread. Use when asked "is this difference real", "did variant B win", or whether a change moved a metric. Says not verified when a group is too small. Not for AI eval runs (use eval-gate) or scoring options (use compare-options).
license: MIT
metadata:
  pack: data
  version: 0.1.0
  needs: python3
---

# Stat compare

Produces a comparison of two groups computed from the rows, with every assumption marked checked, warned or not checked.

## Done when

- `scripts/compare.py` ran on the raw rows, not on summary numbers typed into the chat.
- The reply gives the difference with its interval and the p-value as separate answers: whether it could be chance, and how big it is.
- Every warning the script printed is in the reply.

End in exactly one state: **pass** (compared; samples large enough; independence checked; a stated claim is supported), **fail** (a stated claim is not supported, or units repeat or sit in both groups), **not verified** (a group is too small, or independence was not checked), or **blocked** (columns missing, more than two groups and none named).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| Raw rows: one per measurement, a value column and a group column | the file exists | ask for the export; summaries are not enough; end as blocked |

## Steps

The script is `scripts/compare.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/compare.py"`.

1. **Check needs.** Find the column that identifies a unit (user, account, patient). Without it independence cannot be checked.
2. **State the claim before looking**, if there is one: `differ`, `a-higher` or `b-higher`.
3. **Compare.**
   ```
   python3 scripts/compare.py <file> --value <column> --group <column> --unit <column> [--a X --b Y] [--claim b-higher]
   ```
   The seed is fixed, so the same data prints the same numbers.
4. **Read the warnings.** Small sample: one or two rows can move the result. Heavy skew: compare the medians too. Unequal spread: the groups differ in more than level. Lopsided split: ask how rows were assigned.
5. **Report.** End state first. Then group sizes, the difference with its interval, p-value, effect size, then the warnings and what was not checked.

## Rules

- No evidence of a difference is not proof that the groups are equal. Never write it as such.
- Do not re-run with other columns, subsets or claims until one passes. If the user asks for several comparisons, say that each extra test raises the chance of a false hit.
- Thresholds are in `references/limits.json` and are unverified defaults; alpha is the user's to set.
- This compares two groups. Sample-size planning and models with several factors are outside it; say so.

## Not for

- Comparing AI eval runs against a baseline → use `eval-gate`.
- Weighing options for a decision → use `compare-options`.
- Describing one dataset → use `data-profile`.

## Level

- beginner: explain the p-value, the interval and the effect size in one sentence each.
- standard: as written.
- expert: the comparison block, the warnings and the RESULT line. Every assumption check still runs.

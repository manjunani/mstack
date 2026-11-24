---
name: judge-check
description: Tests whether an LLM grader can be trusted, by comparing its verdicts with examples a person labelled and reporting agreement, a confusion table, Cohen's kappa and every disagreement. Use when an eval is scored by a model, a judge prompt or rubric was written or changed, or the user asks "can I trust my LLM judge?" or "does the grader agree with me?". Not for comparing two eval runs (use eval-gate) or for writing the cases to grade (use test-cases).
license: MIT
metadata:
  pack: ai
  version: 0.2.1
  needs: python3
---

# Judge check

Produces a measured answer to "does this grader label examples the way a person does?", with the examples where it does not.

## Done when

- `agree.py` ran on at least 30 examples that a person labelled, with every outcome the grader can give present at least five times, and its `RESULT` line is quoted in the reply.
- The reply gives the agreement rate, kappa, and the direction of the errors (what the grader passed that the person failed, and the reverse).
- Every disagreement the script listed was read, and the reply says for each group whether the grader or the label looks wrong.

End in exactly one state: **pass**, **fail**, **not verified** (say whether examples, a rare label or a missing verdict file is the gap), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| Human labels | a JSON lines file with `id` and `human` | ask the user to label examples; a model's labels do not count; end as blocked |
| Grader verdicts on the same examples | the same file with `judge`, or a second file with `id` and `judge` | ask before running the grader, because that run calls a paid model; end as blocked if the user says no |

One row per example: `{"id": "ex-01", "human": "pass", "judge": "fail", "category": "refunds"}`. This skill does not run the grader and calls no model.

## Steps

The script is `scripts/agree.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/agree.py"`.

1. **Check needs.** Ask who wrote the labels and whether that person saw the grader's verdicts first. Labels written after seeing the verdicts lean towards them; say so in the report.
2. **Measure.**
   ```
   python3 scripts/agree.py <examples.jsonl>
   python3 scripts/agree.py --labels <labels.jsonl> --verdicts <verdicts.jsonl>
   ```
3. **Read what it printed.**

   | Output | What to look for |
   |---|---|
   | agreement and its interval | A wide interval means more examples are needed before the figure can be relied on. |
   | Cohen's kappa | Agreement beyond chance. A grader that passes everything can agree 90% of the time and still have a kappa near 0. |
   | confusion table | Which way the grader errs. Passing what a person failed hides regressions; failing what a person passed blocks good changes. |
   | per category | One weak category can hide inside a good overall figure. |
   | `DISAGREE` lines | Open each example. Decide with the user whether the grader or the label is wrong. |
4. **Report.** End state first, then the figures, the direction of the errors, and the disagreements grouped by cause. If the verdict is fail, name the kind of example the grader gets wrong; changing the grader is a separate task.

## Rules

- Labels come from a person. Never fill in, correct or drop a label to raise the figure. A label the user agrees was wrong is changed by the user, and the report says how many were changed.
- A grader verdict that is missing or empty never counts as agreement.
- After the grader prompt is changed, measure it on examples that were not looked at while changing it. A score on the examples used for tuning proves little; say so if that is all there is.
- The floors in `references/defaults.json` are first settings written from memory. The script says so on every run. `--min-examples`, `--min-agreement` and `--min-kappa` are the user's to set, not a way to reach a pass.
- A pass says the grader matches this person on these examples. It says nothing about whether the evaluation cases cover what matters.

## Not for

- Deciding whether a new prompt or model made results worse → use `eval-gate`.
- Writing evaluation or test cases → use `test-cases` if installed; if not, write them with the user first.
- Measuring retrieval → use `rag-check`.
- How to call a model API or write a grader prompt → use the provider's own documentation or skill.

## Level

- beginner: explain kappa with the "grader that passes everything" example, and what each cell of the table means.
- standard: as written.
- expert: the result line, the figures and the disagreement groups only. No check is skipped at any level.

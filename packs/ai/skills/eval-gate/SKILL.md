---
name: eval-gate
description: Decides whether a change to a prompt, model, tool or agent made results worse, by comparing a new evaluation run with a saved baseline, case by case over repeated trials. Use when a prompt was edited, a model is being swapped or upgraded, or the user asks "did my eval get worse?", "is the new prompt better?" or "can I ship this agent change?". Not for checking the grader itself (use judge-check), for retrieval scores alone (use rag-check) or for ordinary code tests (use verify).
license: MIT
metadata:
  pack: ai
  version: 0.2.0
  needs: python3
---

# Eval gate

Produces one verdict on a candidate evaluation run: pass, fail, or "the sample is too small to tell", with the cases that flipped.

## Done when

- `gate.py compare` ran on a baseline file and a candidate file that each hold at least three trials per case, and its `RESULT` line is quoted in the reply.
- Every flipped, missing and less stable case the script printed is named in the reply.
- The record `.mstack/eval-gate/last-compare.json` exists for this comparison.

End in exactly one state: **pass**, **fail**, **not verified** (say whether trials, cases or certainty are short, and how many cases would settle it), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| Results of the trusted version | a JSON lines file, or `.mstack/eval-gate/baseline.jsonl` | ask the user to run their evaluation on the version they trust; end as blocked |
| Results of the changed version | a JSON lines file from the same evaluation set | ask the user to run it; end as blocked |

A results file has one row per trial: `{"case": "refund-01", "trial": 1, "pass": true}` or `"score": 0.8` in place of `pass`. This skill does not run the evaluation and calls no model. Running it is the user's runner, and it costs usage: ask before starting it.

## Steps

The script is `scripts/gate.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/gate.py"`.

1. **Check needs.** Find both result files. If the user's runner writes another shape, convert a copy into the row format above; never edit the runner's own output.
2. **Look at each file.**
   ```
   python3 scripts/gate.py summary <results.jsonl>
   ```
   It prints the pass rate per case, how many cases passed every time and how many passed at least once. Fewer than three trials in a case means the file cannot be used yet.
3. **Keep the baseline** the first time, after the user agrees which run is the trusted one.
   ```
   python3 scripts/gate.py save <baseline.jsonl> --note "<model, prompt version, date>"
   ```
4. **Compare.**
   ```
   python3 scripts/gate.py compare --candidate <candidate.jsonl> [--baseline <file>] [--critical <case> ...]
   ```
   The script averages the trials inside each case, pairs the cases, and prints the difference with a 95% interval.
5. **Read the lines above the result.**

   | Line | Meaning |
   |---|---|
   | `FLIP` | The case went from mostly passing to mostly failing, or the other way. Open its outputs. |
   | `LESS STABLE` | It passed every time before and no longer does. |
   | `MISSING` | A baseline case is absent from the candidate. This fails the gate. |
   | `NEW` | Only in the candidate. It is not compared. |
6. **Report.** End state first, then the two overall rates, the difference and its interval, then every flipped, missing and less stable case. For "not verified", give the number of cases the script says would settle it.

## Rules

- The verdict is the script's. Do not round a "not verified" up to a pass because the difference looks small.
- Never delete a case, edit a row or drop a trial to change the result. `--retired`, `--max-drop`, `--min-cases` and `save --replace` change what counts as a pass: use them only when the user decided so, and say in the report that they were used.
- A pass says the candidate is not worse on these cases. It does not say the cases cover what matters.
- If a model grades the cases, the result is only as good as that grader. Check the grader with `judge-check` if it is installed; if not, state that the grader was not checked.
- The defaults in `references/defaults.json` are first settings, not measured values. The script says so on every run.
- This skill measures results. For how to call a model API, cache prompts or migrate between models, use the provider's own documentation or skill.

## Not for

- Finding out whether an LLM grader can be trusted → use `judge-check`.
- Scoring retrieval alone (hit rate, rank) → use `rag-check`.
- Running a project's unit tests or build → use `verify`.
- Writing the evaluation cases → use `test-cases` if installed.

## Level

- beginner: explain why one run per case proves nothing, what the interval means, and what each printed line stands for.
- standard: as written.
- expert: the result line, the two rates, the interval and the flagged cases only. No check is skipped at any level.

---
name: rag-check
description: Measures whether retrieval returns the passage that holds the answer, from a gold set of questions and the ranked ids a retriever returned, with hit rate at k, mean reciprocal rank, the misses and the change against a saved baseline. Use when chunking, embeddings, an index or a reranker changed, or the user asks "is my RAG finding the right chunks?" or "did retrieval get worse?". Not for judging the generated answers (use eval-gate) or for checking an LLM grader (use judge-check).
license: MIT
metadata:
  pack: ai
  version: 0.2.1
  needs: python3
---

# RAG check

Produces retrieval figures for one gold set (hit rate at k, MRR), the questions whose passage was missed, and a verdict against a floor or a baseline.

## Done when

- `score.py score` ran on a gold file and the retriever's ranked ids for the same questions, and the reply quotes its `RESULT` line.
- Every `MISS`, `NEWLY MISSED` and `NOT ANSWERED` line is named in the reply.
- The verdict was judged against a floor the user set or a saved baseline; with neither, the state is not verified.

End in exactly one state: **pass**, **fail**, **not verified** (too few questions, questions without results, or nothing to judge against), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| A gold set | JSON lines: `id`, `question`, `answer_id` (the passage that holds the answer) | ask the user. A draft written by the model needs the user's review before it counts; end as blocked until then |
| The retriever's output for those questions | JSON lines: `id`, `retrieved` (ids, best first) | ask the user to run their retriever on the gold questions; this skill calls no search service; end as blocked |

## Steps

The script is `scripts/score.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/score.py"`.

1. **Check needs.** Confirm the k the application really uses: how many passages go into the prompt. Pass it as `--at`.
2. **Score.**
   ```
   python3 scripts/score.py score --gold gold.jsonl --results run.jsonl --at 5 [--floor 0.8]
   ```
   It compares with `.mstack/rag-check/baseline.json` when that exists (`--no-baseline` to skip).
3. **Keep a baseline** once the user agrees the run is the reference.
   ```
   python3 scripts/score.py save --gold gold.jsonl --results run.jsonl --note "<index, embedding model, chunking>"
   ```
4. **Read the misses.** For a few `MISS` lines, open the passages that were returned instead. Common causes to check: the answer is split across chunks, the question uses other words than the passage, or the gold label is wrong. Label errors are the user's to fix.
5. **Report.** End state first, then hit@k and MRR (and the change against the baseline), then the misses and newly missed questions.

## Rules

- A question with no results row is "not answered", never a miss and never a pass.
- Never change gold labels, drop questions or raise k to reach a pass. `--retired`, `--floor`, `--at` and `save --replace` are the user's decisions; say in the report when they were used.
- Hit rate measures retrieval only. Whether the final answer is right goes through `eval-gate`.
- The defaults in `references/defaults.json` are first settings, not measured values. There is no default floor.

## Not for

- Judging the generated answers → use `eval-gate`.
- Checking an LLM grader against labels → use `judge-check`.
- What retrieval costs in tokens → use `spend-check`.
- How to build an index or call an embedding API → use the provider's own documentation or skill.

## Level

- beginner: explain hit rate at k and reciprocal rank with one question from the user's own set.
- standard: as written.
- expert: the result line, the figures and the missed ids only. No check is skipped at any level.

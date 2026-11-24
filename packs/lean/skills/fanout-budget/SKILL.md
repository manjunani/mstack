---
name: fanout-budget
description: Estimates the token cost of a batch of subagents or eval runs from past runs, sets a limit the user agrees to, and checks it before each new launch so a fan-out stops before it overshoots. Use when about to start several agents in parallel, run an eval many times, or the user says "don't let this burn my usage" or "how much will 10 agents cost?". Not for an app's own API bill (use spend-check) or for hosting costs (use cost-watch).
license: MIT
metadata:
  pack: lean
  version: 0.2.2
  needs: python3
---

# Fan-out budget

Produces a budget file for one batch of launches and a yes or no before each launch, based on tokens measured in transcripts.

## Done when

- `budget.py estimate` ran and the reply showed the per-run figure and its source (past runs, or the user's figure).
- The user named a limit, and `budget.py set` wrote `.mstack/fanout-budget.json`.
- Before every launch in the batch, `budget.py check --launches N --record` ran and passed. A failed check stopped the launches.

End in exactly one state: **pass** (all launches fit), **fail** (a check refused a launch; say how many fit), **not verified** (launches went ahead without a check), or **blocked** (no per-run figure, no limit, or no budget file).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| A per-run figure | past subagent runs in this project's transcripts, or `--per-run` from the user | ask the user for a figure; end as blocked |
| A limit | the user's number of tokens for the batch | ask; do not invent one |

## Steps

The script is `scripts/budget.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/budget.py"`.

1. **Estimate.** Count the launches planned, then:
   ```
   python3 scripts/budget.py estimate --launches 8
   ```
   It uses the 90th percentile of past subagent runs in this project. Add `--all-projects` if this project has few, or `--per-run <tokens>` when the user knows better (for eval runs, which are not subagents).
2. **Ask for a limit.** Show the estimate and ask the user for the limit of the batch. Do not pick it.
3. **Set it.**
   ```
   python3 scripts/budget.py set --limit 2000000
   ```
4. **Check before each launch.** Before starting one or more agents or runs:
   ```
   python3 scripts/budget.py check --launches 2 --record
   ```
   Exit 0: launch them. Exit 1: do not launch; report how many still fit and ask the user whether to raise the limit, launch fewer or stop.
5. **Report.** End state first, then launches made, tokens measured so far and room left.

## Rules

- A run's tokens are input, cache read, cache write and output over its messages, measured from its transcript after it starts. Until then a recorded launch counts at the per-run figure.
- Never raise the limit or edit the budget file by hand to get a pass. A new limit comes from the user, through `set`.
- Each launch is checked, including launches made later by a subagent's own fan-out, when that subagent can run the script.
- The script writes only `.mstack/fanout-budget.json`.

## Not for

- An app's own API usage and price → use `spend-check`.
- A cloud or hosting bill → use `cost-watch`.
- Splitting work between agents → use `parallel` if installed.
- Total use over days → use `usage-report`.

## Level

- beginner: explain why each agent re-reads its own context and why a batch multiplies it.
- standard: as written.
- expert: the check result line only before each launch. No check is skipped at any level.

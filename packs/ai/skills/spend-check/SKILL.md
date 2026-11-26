---
name: spend-check
description: Measures the tokens and cost of an AI flow from its own usage log and compares them with a budget, with totals by model or feature tag, the cache read share, and rows without a price kept apart. Use when the user asks "how much does this agent cost per run?", "are we over budget on tokens?" or "did caching cut the bill?", or before a flow goes to production. Not for a cloud or hosting bill (use cost-watch) or for how to set up prompt caching (use the provider's own documentation or skill).
license: MIT
metadata:
  pack: ai
  version: 0.3.1
  needs: python3
---

# Spend check

Produces token and cost totals for one usage log and a verdict against a budget the user set.

## Done when

- `spend.py` ran on the usage log with a budget, and the reply quotes its `RESULT` line.
- The reply says which prices were not verified and repeats the script's note to check the provider's pricing page.
- Rows with no price and lines that could not be read are named, not folded into the total.

End in exactly one state: **pass**, **fail**, **not verified** (no budget, unread lines, unpriced models or unverified prices), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| A usage log | JSON lines with `model` and token counts from each response's usage block | ask the user to log the usage block of each response for one run; nothing can be measured without it; end as blocked |
| Prices | `references/prices.json`, or a copy the user filled in | the shipped file holds placeholders only; see step 2 |
| A budget | per run, per request or in total, in money or tokens | ask the user; without it the result is not verified |

## Steps

The script is `scripts/spend.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/spend.py"`.

1. **Check needs.** Ask what one "run" of the flow is and whether the log marks it with a `run` field.
2. **Prices.** The shipped `references/prices.json` holds example models with prices written from memory, all `"verified": false`. Ask the user to copy it into their project (for example `.mstack/spend-check/prices.json`), enter the prices from the provider's pricing page with the date, and set `verified` to true. Never present a remembered price as a fact.
3. **Measure.**
   ```
   python3 scripts/spend.py usage.jsonl --prices <prices.json> --budget 0.50 --per run
   python3 scripts/spend.py usage.jsonl --prices <prices.json> --budget-tokens 200000 --by tag
   ```
4. **Read the table.** Look at which model or tag holds most of the cost, the cache read share, and any `UNKNOWN COST`, `NOT READ` or `WARNING` lines.
5. **Report.** End state first, then the figure compared with the budget, the largest groups, the cache read share, and what was not verified. Ways to cut cost are suggestions after the report; this skill only measures.

## Rules

- "Missing" is not "zero". A row with no price or no token counts stays outside the total, and the report says the real figure is higher.
- A cost figure built on unverified prices is an estimate. Say so in the same sentence as the figure.
- One run is a sample. If the user wants a per-run figure for planning, ask for several runs in the log.
- This skill reads a log. It calls no API, and it does not count tokens of text itself.

## Not for

- A cloud, hosting or database bill → use `cost-watch` if installed.
- How to set up prompt caching, count tokens before a request, or choose a model → use the provider's own documentation or skill.
- Why one agent run used so many turns → use `trace-triage`.
- Whether a cheaper model still gives good results → use `eval-gate`.

## Level

- beginner: explain input, output, cache read and cache write tokens, and why prices must come from the provider's page.
- standard: as written.
- expert: the result line, the table and the unverified prices only. No check is skipped at any level.

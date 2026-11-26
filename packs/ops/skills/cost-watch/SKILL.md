---
name: cost-watch
description: Reads a usage or billing export (CSV or JSON), sums it by service and day, projects the month and compares it with the limit the user states, and names the service whose spend grew most. Calls no provider API. Use when the user asks "are we going over budget?", "why did the bill jump?" or "what will this month cost?", or hands over a hosting or cloud usage export. Not for tokens and cost of an AI flow (use spend-check) or for speed targets (use nfr-budgets).
license: MIT
metadata:
  pack: ops
  version: 0.3.1
  needs: python3
---

# Cost watch

Produces spend per service for the month, a projection for the whole month, the largest growth, and a verdict against the user's limit.

## Done when

- The script read the export the user supplied and printed how many rows it could not read.
- Spend so far and the projection were compared with a limit the user stated.
- The largest growth is named with its two windows and amounts, flagged or not.
- The reply quotes the script's figures, not figures worked out by hand.

End in exactly one state: **pass** (under the limit now and projected), **fail** (over now, or projected over), **not verified** (no limit given, or too few days to project), or **blocked** (no export, unreadable columns, mixed currencies).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| A usage or billing export | a CSV or JSON file the user downloaded | ask for it; end as blocked |
| The monthly limit | the user states it, in the export's currency | ask; without it the result is not verified |

## Steps

The script is `scripts/usage.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/usage.py"`.

1. **Get the export.** Ask the user to download the usage or billing export for this month from each provider's billing page. Do not log in to a provider, call its API or run its CLI to fetch it unless the user asks and says yes to the exact command. One provider per run.
2. **Get the limit.** Ask for the monthly limit and the currency. Do not invent one.
3. **Run.**
   ```
   python3 scripts/usage.py exports/hosting-2026-11.csv --limit 40
   ```
   If the script cannot tell the columns apart, it lists them: pass `--date-col`, `--service-col` and `--cost-col`. Use `--month 2026-10` to judge an earlier month, `--window 14` for a slower-moving bill.
4. **Read the output.**
   - Rows without a readable date or amount are skipped and counted. If that count is large, the result is not trustworthy: say so.
   - The projection assumes the last days' average holds. A spike on the last day pushes it up; say so if you see one.
   - *FLAG* growth passed both floors in `references/floors.json` (unverified defaults). *note* growth did not.
5. **Look at the flagged service** if the user wants a cause: compare its daily rows, and with the user's yes read its logs (`log-triage`) or its configuration. Changing a plan, a limit or a setting on the provider is the user's action.
6. **Report.** End state first, then spend so far, projection, limit, the largest growth with both windows, the skipped-row count, and that the figures come only from this export.

## Rules

- The limit comes from the user. A pass without a limit is impossible; the script ends not verified.
- Never add, guess or round figures yourself. Quote the script.
- An export covers what the provider put in it. Taxes, credits and other providers may be missing; say so.
- Never send the export anywhere, and never paste account ids or card details from it into the reply.

## Not for

- Tokens and cost of an AI or LLM flow → use `spend-check`.
- Speed or size targets → use `nfr-budgets`.
- Why a service throws errors → use `log-triage`.

## Level

- beginner: explain how the projection is made and what the two floors mean.
- standard: as written.
- expert: the totals, the projection, the flag and the `RESULT` line. Step 2 is asked at every level.

---
name: usage-report
description: Turns local Claude Code transcripts into a token table per project and per day (input, output, cache read, cache write) and lists the sessions that used the most. Use when the user asks "where did my usage go this week?", "which project eats the most tokens?" or "show my Claude Code token use by day", or hit a usage limit and wants to know why. Read-only and local. Not for an app's own API costs (use spend-check) or for the size of the session open now (use session-check).
license: MIT
metadata:
  pack: lean
  version: 0.2.1
  needs: python3
---

# Usage report

Produces token tables by project, by day and by session from the usage fields in local transcripts.

## Done when

- `usage.py` ran over a period the user accepted, and the reply quotes its `RESULT` line.
- The reply shows the project and day tables, the top sessions, and the cache read share.
- The reply says the figures are tokens from local transcripts, not a bill.

End in exactly one state: **pass** (tables made, within a limit if one was given), **fail** (over the user's limit), **not verified** (no usage fields in the period), or **blocked** (no transcript folder).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| Transcripts | `~/.claude/projects` exists | ask where the transcripts are and pass `--projects-dir`; end as blocked |

## Steps

The script is `scripts/usage.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/usage.py"`.

1. **Check needs.** Ask for the period if the user named one ("this week" is `--days 7`).
2. **Count.**
   ```
   python3 scripts/usage.py --days 7
   python3 scripts/usage.py --days 30 --project-name <folder name> --top 5
   python3 scripts/usage.py --days 30 --limit 50000000
   ```
3. **Read the tables.** Look at which project and which days hold most of the total, and at the top sessions. A high cache read share is normal in long sessions: it is the re-reading of earlier context, and the main thing a hand-off or a smaller start cuts.
4. **Point to the cause.** For a heavy start in every session, suggest `context-audit`; for one very long session, `session-check`; for many subagents, `fanout-budget`. Name them only if installed; otherwise describe the cause.
5. **Report.** End state first, then the tables (or their top rows), the top sessions and the cache read share.

## Rules

- Tokens only. Do not turn them into money; plans and prices differ, and this skill has no price data.
- Each reply is counted once even when the transcript repeats it over several lines; do not add figures by hand.
- Never print message text, and never copy transcripts anywhere. The tables stay in the reply.
- Older transcripts may have been cleaned up by the client; say that the report covers what is on disk.

## Not for

- An app's own API usage and its price → use `spend-check`.
- A cloud or hosting bill → use `cost-watch`.
- The session open now → use `session-check`.

## Level

- beginner: explain input, output, cache read and cache write, and why cache reads grow with session length.
- standard: as written.
- expert: the project table and the result line only. No check is skipped at any level.

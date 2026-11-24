---
name: session-check
description: Reads the current Claude Code session's transcript and reports how many tokens each new message re-reads, how fast that grew and the file size, then says whether to hand off and start fresh. Use when the user asks "is this chat getting too long?", "should I start a new session?" or "how big is this session?", or replies are slowing down after many turns. Not for writing the hand-off note itself (use handoff) or for token totals across past sessions (use usage-report).
license: MIT
metadata:
  pack: lean
  version: 0.2.2
  needs: python3
---

# Session check

Produces the size of one session in tokens re-read per message, measured from the transcript's own usage fields, and a verdict against a hand-off line.

## Done when

- `session.py` ran on the current session's transcript, and the reply quotes its `RESULT` line.
- The reply gives the re-read figure now, the first-turn figure and the line it was compared with.
- On a fail, the reply names the next step: the `handoff` skill if installed, or a written note and a fresh session.

End in exactly one state: **pass** (below the hand-off line; mention a warning if the script printed one), **fail** (at or over it: hand off), **not verified** (the transcript has no usage fields), or **blocked** (no transcript found).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| The session transcript | newest `.jsonl` in `~/.claude/projects/<folder-slug>/`, found by the script | ask the user for the path; end as blocked |

## Steps

The script is `scripts/session.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/session.py"`.

1. **Check needs.** The script finds the newest transcript for the folder Claude Code was started in. If the session was started elsewhere, pass `--project <that folder>` or the `.jsonl` path.
2. **Measure.**
   ```
   python3 scripts/session.py
   python3 scripts/session.py --project <folder> --handoff-at 120000
   ```
   The lines come from `references/thresholds.json` and are starting points, not limits of the platform. If the user knows their model's window or the point where their client compacts, pass `--warn-at` and `--handoff-at`.
3. **Read the numbers.** "Re-read now" is what every next message costs on the input side. Large growth over the last five turns means big tool output or file reads are piling up.
4. **Advise.** On a fail: hand off at the next natural break, not in the middle of an edit. Use the `handoff` skill if it is installed. If it is not, write the goal, what is verified, what is not, and the next step into a file, and start a new session that reads it.
5. **Report.** End state first, then the figures and the next step.

## Rules

- The figures come from the usage fields in the transcript. Never estimate them from the text length when usage fields are there.
- Never print or quote message text from the transcript. Counts only.
- Do not start a hand-off or a new session on the user's behalf; say when and how.
- A pass with a warning is still a pass. Mention the warning once.

## Not for

- Writing the hand-off note → use `handoff`.
- Saving one decision for later sessions → use `remember`.
- Token totals over days or projects → use `usage-report`.
- What loads before the first message → use `context-audit`.

## Level

- beginner: explain why every message re-reads the whole session and why a fresh session with a note is cheaper.
- standard: as written.
- expert: the result line and the re-read figure only. No check is skipped at any level.

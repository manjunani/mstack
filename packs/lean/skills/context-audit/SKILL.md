---
name: context-audit
description: Measures what Claude Code loads before the first message, ranks the biggest items in estimated tokens and says what to switch off. Use when a new session already feels heavy, the user asks "why is my context so full at the start?" or "which plugins cost the most?", or wants a leaner setup. Covers CLAUDE.md and AGENTS.md with their @-imports, plugin skill listings, MCP servers, output style and hooks. Not for one long session (use session-check) or for vetting a skill's safety (use skill-check).
license: MIT
metadata:
  pack: lean
  version: 0.3.1
  needs: python3
---

# Context audit

Produces a ranked list of everything that fills a Claude Code session before the user types, with an estimated token size and a way to switch off each item, compared with a budget.

## Done when

- `audit.py` ran on the right home and project folder, and the reply quotes its `RESULT` line.
- The reply names the top items by estimated tokens, each with the switch-off step the script printed.
- Every size is called an estimate, and the items the script marks `NOT MEASURED` (MCP tool schemas, hook output) are listed as not measured.

End in exactly one state: **pass** (within the budget, or nothing loads), **fail** (over the budget), **not verified** (say which items could not be measured, when they could change the verdict), or **blocked** (folder missing).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| The home and project folders | the folders exist | ask for the right paths; end as blocked |
| A budget | the user's figure, or the unverified default in `references/thresholds.json` | use the default and say it is a starting point |

## Steps

The script is `scripts/audit.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/audit.py"`.

1. **Check needs.** Ask which project folder to audit if it is not the current one.
2. **Measure.**
   ```
   python3 scripts/audit.py --project <folder>
   python3 scripts/audit.py --project <folder> --budget 15000 --top 15
   ```
   It reads files only. It reads transcript tool names (not text) to count MCP tools seen; add `--no-transcripts` if the user does not want that.
3. **Read the ranking.** The top of the list is where cuts pay off: a large @-import, a plugin with many skills, a long CLAUDE.md. Look at the repeated paragraphs line: the same text in two instruction files is paid twice.
4. **Propose cuts.** For each of the top items, repeat the step the script printed (disable a plugin, drop an import, move detail out of CLAUDE.md). Ask which ones the user wants; this skill changes nothing itself.
5. **Report.** End state first, then the estimated total against the budget, the top items with their steps, and what was not measured.

## Rules

- Sizes are characters divided by four. Say "about" or "estimated" next to every token figure.
- Never edit settings, CLAUDE.md files or plugin state. Print the change; the user makes it.
- A plugin's cost is the sum of its skills, commands and agents. Judge it as a whole, then ask whether it is used.
- An MCP server's tool schemas are not in any file this script can read. For which servers are idle, use `mcp-trim` if installed; otherwise list them and say their size is unknown.
- Do not paste the content of instruction files into the reply. Names and sizes are enough.

## Not for

- How big the current session has grown → use `session-check`.
- Whether a skill or plugin is safe to install → use `skill-check`.
- Which MCP servers are never called → use `mcp-trim`.
- Token use over past days and projects → use `usage-report`.

## Level

- beginner: explain what loads at the start of every session and why a smaller start makes every message cheaper.
- standard: as written.
- expert: the result line, the top five and the not-measured list only. No check is skipped at any level.

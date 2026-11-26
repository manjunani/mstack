---
name: mcp-trim
description: Lists the MCP servers Claude Code loads and counts how often each one's tools were really called in past transcripts, then prints the exact command or setting to turn off the idle ones. Use when the user asks "which MCP servers do I actually use?", "can I drop some MCP tools?" or wants fewer tools loaded in every session. Changes nothing itself. Not for testing an MCP server you are building (use mcp-check) or for sizing everything else that loads at the start (use context-audit).
license: MIT
metadata:
  pack: lean
  version: 0.3.0
  needs: python3
---

# MCP trim

Produces a table of configured MCP servers with their call counts over a period, and for each idle server the exact change that turns it off.

## Done when

- `mcptrim.py` ran over a period the user accepted, and the reply quotes its `RESULT` line.
- Each idle server is listed with the command or setting the script printed, and the user is told to make the change.
- No setting, config file or plugin state was changed by this skill.

End in exactly one state: **pass** (every server was called, or none is configured), **fail** (idle servers found; list them), **not verified** (no transcripts in the period), or **blocked** (bad input).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| Transcripts | `.jsonl` files under `~/.claude/projects` from the period | widen `--days`, or end as not verified |

## Steps

The script is `scripts/mcptrim.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/mcptrim.py"`.

1. **Check needs.** Ask how far back to look if the user has a view; the default is 30 days.
2. **Count.**
   ```
   python3 scripts/mcptrim.py
   python3 scripts/mcptrim.py --days 90 --project <folder>
   python3 scripts/mcptrim.py --this-project-only
   ```
   By default calls are counted across every project's transcripts, because a user-scope server is loaded everywhere. Use `--this-project-only` for servers that belong to one project.
3. **Read the table.** A server with zero calls is a candidate. One with few calls may still matter (a deploy tool used monthly): ask before suggesting it goes.
4. **Show the changes.** Repeat the command or setting the script printed for each candidate the user wants gone. Plugin servers go away only with their plugin; say what else that plugin brings.
5. **Report.** End state first, then idle servers with their changes, and any servers seen in transcripts but not in config.

## Rules

- Never run `claude mcp remove`, edit `.mcp.json`, settings or `~/.claude.json`, or disable a plugin. Print the change; the user makes it.
- Zero calls in a short period is weak evidence. Name the period next to every zero.
- A project `.mcp.json` server is shared with teammates. Prefer the local disable setting the script prints over deleting it.
- Count only. Never quote tool inputs or results from transcripts.

## Not for

- Testing an MCP server you are building → use `mcp-check`.
- Everything else that loads at the start of a session → use `context-audit`.
- Whether a plugin or skill is safe → use `skill-check`.

## Level

- beginner: explain that every loaded server's tool list takes room in each session, used or not.
- standard: as written.
- expert: the idle servers and their changes only. No check is skipped at any level.

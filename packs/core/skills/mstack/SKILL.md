---
name: mstack
description: Looks up which mstack skill or pack fits a task, from the generated map of every skill, and gives the install line for a pack that is missing. Use when the user asks "is there a skill for this?", "which skill should I use?", "what can mstack do?", or wants to see the list of packs or skills. Not for doing the task itself: this only names a skill, it never starts one.
license: MIT
metadata:
  pack: core
  version: 0.3.0
  needs: python3
---

# mstack

Produces one recommended skill with the reason, or the plain answer that no skill fits.

## Done when

- The reply names at most one skill to use, why it fits, and the pack's install line if the pack may not be installed.
- Or it says that no mstack skill fits, which is a complete answer.
- Nothing was started.

End in exactly one state: **pass** (a skill was named, or none fits), **fail**, **not verified**, or **blocked** (the map is missing; say so).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| The skill map | `references/skills.json` in this skill's folder | end as blocked; the pack was not installed completely |

## Steps

The script is `scripts/find.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/find.py"`.

1. **Search with the user's own words** for the task, not with skill names you remember.
   ```
   python3 scripts/find.py search <words describing the task>
   python3 scripts/find.py packs              # when the user asks what exists
   python3 scripts/find.py list --pack test   # one pack's skills
   ```
2. **Read the descriptions** of what came back, including each "Not for" line. The search matches words; you judge the fit.
3. **Pick at most one.** If two fit, choose the one whose "Use when" matches the user's situation and mention the other in one clause. If none fits, say so.
4. **Check its needs** against what the user has (a tool, a browser, an API key) and say what is missing.
5. **Answer** in this shape: the skill, one sentence on why, what it needs, and the install line when the pack is not installed. Then stop.

## Rules

- This skill recommends and never runs the skill it names. The user, or their next message, starts it.
- "No skill fits" is a good answer. Do not stretch a skill over a task it was not written for.
- Do not list more than three skills. A long list is the problem this skill exists to remove.
- The map shows each skill's test results. If a skill is "not tested", say so.
- Do not use this skill when a task is already clear and an installed skill obviously fits. It answers questions about skills; it is not a gate in front of every task.

## Not for

- Doing the task → use the skill it names.
- Checking whether a third-party skill is safe → use `skill-check`.

## Level

- beginner: add one sentence on what a skill and a pack are, the first time.
- standard: as written.
- expert: the skill name, pack and install line only. The search is never skipped in favour of memory.

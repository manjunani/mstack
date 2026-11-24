---
name: tool-lint
description: Checks tool definitions before a model sees them and flags names that are unclear or collide, descriptions that do not say when to use the tool, missing required lists, untyped parameters and pairs of tools whose descriptions overlap. Use when tools or function schemas for an agent were written or changed, the model keeps picking the wrong tool, or the user asks "are my tool definitions good?". Not for a running MCP server (use mcp-check) or for vetting someone else's skill or plugin (use skill-check).
license: MIT
metadata:
  pack: ai
  version: 0.2.2
  needs: python3
---

# Tool lint

Produces a list of FAIL and WARN lines for a set of tool definitions, each naming the tool and the rule.

## Done when

- `lint.py` ran on every file that holds the tool definitions, and the reply quotes its `RESULT` line.
- Every FAIL line is in the reply with the tool it names.
- WARN lines are shown as judgement calls, not as defects.

End in exactly one state: **pass** (no FAIL line; say how many WARN lines remain), **fail**, **not verified** (say which definitions could not be put in front of the script), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| The definitions as JSON | a file with a list of tools: name, description, and `input_schema`, `inputSchema` or `parameters` | see step 1; if they cannot be exported, end as blocked |

## Steps

The script is `scripts/lint.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/lint.py"`.

1. **Check needs and find the definitions.** If they are already JSON, use that file. If they sit in code as a literal list, copy the list into a new JSON file under `.mstack/tool-lint/` and leave the source alone. If code builds them at run time, ask the user to dump what is really sent to the model. Do not retype definitions from reading the code; a copy made by hand is not what the model sees. Definitions that could not be exported are not verified.
2. **Lint.**
   ```
   python3 scripts/lint.py <tools.json> [<more.json> ...]
   python3 scripts/lint.py <tools.json> --strict        # WARN lines fail too
   ```
3. **Read the FAIL lines first.** They are facts: a duplicate or colliding name, no description, no schema, a parameter with no type, a required list that names a parameter that does not exist, an empty enum, two descriptions that are the same text.
4. **Read the WARN lines with the user.** They are judgement: an unclear name, a description that is short or does not say when to use the tool, no required list, a parameter without a description, two descriptions that overlap. For an overlapping pair, the useful question is "what would make a model pick the second one?".
5. **Report.** End state first, then the FAIL lines, then the WARN lines grouped by tool, then the total size the script printed. Offer a rewrite for each FAIL. Change the definitions only if the user asked for fixes, and lint again afterwards.

## Rules

- A clean lint shows the definitions are well formed and distinct on paper. Whether a model picks the right tool is behaviour: measure it on cases with `eval-gate` if installed, and say that it was not measured here.
- Never rename a tool or a parameter without the user's yes. Callers and saved prompts depend on the names.
- Facts fail, taste warns. Do not present a WARN as an error, and do not use `--strict` unless the user wants warnings to block.
- The overlap figure counts shared words. Two tools can share few words and still do the same job; say so when a pair looks alike to you and the script is silent.
- The thresholds and the name limits in `references/limits.json` are unverified. The name limits are provider rules written from memory: check the provider's tool-use documentation before quoting them.
- The size figure is characters. For token counts and for how to write tool definitions for a given API, use the provider's own documentation or skill.

## Not for

- An MCP server that can be started and called → use `mcp-check`.
- A skill or plugin from someone else, before installing it → use `skill-check`.
- Why an agent chose a tool badly in one recorded run → use `trace-triage`.
- A review of the code that implements the tools → use `review` if installed.

## Level

- beginner: explain why a model only sees the name, description and schema, and show one rewritten description as an example.
- standard: as written.
- expert: the result line and the FAIL and WARN lines only. No check is skipped at any level.

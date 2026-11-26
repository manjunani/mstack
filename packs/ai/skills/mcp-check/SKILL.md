---
name: mcp-check
description: Proves a stdio MCP server works by starting it, running the initialize and tools/list exchange, checking that every tool's input schema is well formed, and calling the tools the user names to compare each answer with its schema. Use when an MCP server was built or changed, a client reports "no tools" or a tool call errors, or the user asks "does my MCP server work?". Not for linting a tool definition file with no server running (use tool-lint) or for testing a REST API (use api-check).
license: MIT
metadata:
  pack: ai
  version: 0.3.1
  needs: python3, the server's own runtime
---

# MCP check

Produces a per-tool record for one MCP server: schema well formed or not, called or not, answer correct or not.

## Done when

- `probe.py` started the server, and the reply quotes its `RESULT` line.
- Every `TOOL` line shows a well formed schema, or the failing tool and rule are named.
- Every tool the user named has a `CALL` line that reads `ok`, or its failure is quoted.
- Tools that were not called are listed in the reply as not verified.

End in exactly one state: **pass**, **fail**, **not verified** (say which tools were not called or were held back), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| The command that starts the server | the project's MCP config (`.mcp.json` or the client's config file), or ask | ask the user; do not guess a command; end as blocked |
| The server's runtime (node, python, uv, a binary) | the probe reports "could not be started" | tell the user what is absent; install nothing; end as blocked |
| Tools to call, with arguments | the user names them | run the static part only and end as not verified |

## Steps

The script is `scripts/probe.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/probe.py"`.

1. **Check needs.** Starting the server runs its code with the user's rights, so start only a server the user wrote or chose. If it needs keys, the user sets them in the shell environment; never put a secret value on the command line or in the reply.
2. **Run the static part.** It starts the server, does the handshake, lists the tools and checks each schema. No tool is called.
   ```
   python3 scripts/probe.py --server "<start command>"
   ```
   Without calls it ends as not verified. That is expected at this step.
3. **Choose the calls with the user.** Pick tools the `TOOL` lines mark read-only, and arguments whose right answer the user knows. Write them to a new file:
   ```json
   [{"tool": "add", "arguments": {"a": 1, "b": 2}, "expect_contains": "3"},
    {"tool": "add", "arguments": {"a": "x"}, "expect_error": true}]
   ```
4. **Run the calls.**
   ```
   python3 scripts/probe.py --server "<start command>" --calls-file calls.json
   python3 scripts/probe.py --server "<start command>" --call <tool> '<JSON arguments>'
   ```
   The probe checks the arguments against the input schema before sending, and the answer against the output schema when the tool declares one.
5. **Tools that change something.** A named tool that is not marked read-only is held back. Ask the user about each such tool by name, and say what it would change and on which account or data. Only after a yes, run again with `--allow-write`, against test data.
6. **Report.** End state first. Then one line per tool: schema, called or not, result. Quote each `FAIL` line. Name what the probe printed under "not checked" and "NOT CALLED".

## Rules

- Never call a tool the user did not name. Listing tools is not permission to try them.
- "Read-only" is the server's own claim. Read the tool's description before trusting it; if the two disagree, treat the tool as one that writes.
- A pass covers the calls that were made. It does not say a model can choose the right tool; overlapping or vague definitions are a job for `tool-lint`.
- The probe speaks stdio only. For a server reached over HTTP, say that this skill cannot test it and end as blocked.
- The schema check covers `type`, `properties`, `required`, `enum` and `items`. Other keywords are printed as not checked; repeat that in the report.
- The protocol revision in `references/protocol.json` is unverified. The probe prints the revision the server answers with; report that one.
- The server's stderr is saved under `.mstack/mcp-check/`. Quote only the lines that explain a failure; logs can hold secrets.

## Not for

- A tool definition file with no server to run → use `tool-lint`.
- A REST or GraphQL API → use `api-check` if installed; if not, say this skill tests MCP servers only.
- Finding where an agent run using these tools went wrong → use `trace-triage`.
- How to build an MCP server or call a model API → use the provider's own documentation or skill.

## Level

- beginner: explain the handshake, what a schema is, and why tools that write are held back.
- standard: as written.
- expert: the result line and the per-tool table only. No check is skipped and no unnamed tool is called at any level.

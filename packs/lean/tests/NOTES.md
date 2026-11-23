# Test notes: lean pack

Built 2026-11-23. Each script was run on made-up homes, projects and transcripts written by its script test under
`.testrun/` (git-ignored). The test files only build fake data; no real configuration or transcript is copied into
this repository.

Run all script tests from the repository root:

```
cd packs/lean/tests/scripts
python3 context_audit_cases.py ../../../../.testrun/lean-context-audit
python3 session_check_cases.py ../../../../.testrun/lean-session-check
python3 fanout_budget_cases.py ../../../../.testrun/lean-fanout-budget
python3 mcp_trim_cases.py ../../../../.testrun/lean-mcp-trim
python3 usage_report_cases.py ../../../../.testrun/lean-usage-report
```

| Skill | Script | Script test cases | Result |
|---|---|---|---|
| context-audit | `audit.py` | 10 | 10 ok |
| session-check | `session.py` | 11 | 11 ok |
| fanout-budget | `budget.py` | 20 | 20 ok |
| mcp-trim | `mcptrim.py` | 11 | 11 ok |
| usage-report | `usage.py` | 9 | 9 ok |

Each script was also run once, read-only, on a real Claude Code setup to confirm it reads the real file shapes:
all five finished with a `RESULT` line and no error. Their output is not recorded here.

## What the script tests cover

- **context-audit:** @-imports followed and ranked, imports inside code fences ignored, plugin skills summed per
  plugin, a disabled plugin left out, folded YAML descriptions read, AGENTS.md counted with its note, auto memory
  index, output style file, SessionStart hooks listed as not measured (PreToolUse hooks not listed), MCP servers
  from user, local, project and plugin sources with tool counts from transcripts, repeated paragraphs, budget pass
  and fail, the unverified default budget, an empty setup, a missing folder, broken config files.
- **session-check:** one reply written over two lines counted once, compactions counted, pass, warning zone,
  fail with and without an installed handoff skill, newest transcript chosen for a folder, missing transcript,
  transcript without usage fields, no message text printed.
- **fanout-budget:** median and 90th percentile from past runs, a given per-run figure, all projects, no data
  (blocked), set without a limit (blocked, nothing written), only the budget file written, old runs ignored,
  recorded launches counted until their transcripts appear, a refused launch records nothing, measured runs
  replace reservations, bad numbers and a broken budget file.
- **mcp-trim:** five sources of servers, a project server disabled locally is not counted as loaded, repeated
  lines counted once, plugin servers matched by their tool prefix, connectors seen but not configured, the period
  filter, this-project-only, no servers (pass), no transcripts (not verified), config files left unchanged.
- **usage-report:** per project, per day and top sessions with hand-worked totals, subagent transcripts under
  their parent session, a reply over two lines counted once, the period filter, a project filter, a limit, no usage
  (not verified), missing folder and bad period (blocked), no message text printed.

## Not tested, and why

- Trigger, silence and benefit evals (`tests/<skill>.json`) are written but were not run in this build; they need
  `claude plugin eval` and paid usage. `build_evals.py lean` was run to turn them into eval cases.
- MCP tool schema sizes and the text printed by SessionStart or UserPromptSubmit hooks are not measured: they are
  not in any file. context-audit lists them as not measured.
- Claude Code's own rules for which instruction files load (for example whether AGENTS.md is read, or folders above
  the home folder) can change between versions. context-audit counts AGENTS.md and says so, and stops its walk up
  the folder tree at the home folder when the project is inside it.
- The JSON shape of transcripts is not a published format. The scripts read only `type`, `timestamp`, `cwd`,
  `message.id`, `message.usage` and tool-use names, and skip lines they cannot read.
- The thresholds in `references/thresholds.json` are mstack starting points, all `verified: false`.

## Decisions

- fanout-budget does not add `.mstack/.gitignore`: the pack's brief limits it to writing its own budget file.
  Users who do not want the file committed add it to their own ignore file.
- Names follow the agreed skill list; no renames.

## Hooks

- `hooks/session_notice.py` (Stop) and `hooks/agent_budget.py` (PreToolUse on Agent and Task): 15 script cases in `tests/scripts/hook_cases.py`, all passing: silence below the limit, one notice per step, the budget ask with numbers, recording of allowed launches, the off switch, and failing open on bad input or a broken budget file. The session notice was also run once, read-only, on a real session transcript. Not tested: the hooks inside a live Claude Code session; the Stop hook reads only the last reply's usage, so a session that just compacted is measured after its next reply.

---
name: trace-triage
description: Reads the saved trace of an agent run and names where it went wrong, with line numbers for the first failing step, repeated identical tool calls, tool errors the agent ignored, turns with no progress and the largest context contributors. Use when an agent got stuck, looped, burned its turns, gave up or claimed success after an error, or the user asks "why did the agent do that?". Not for server or application logs (use log-triage), for bugs in ordinary code (use debug) or for token cost against a budget (use spend-check).
license: MIT
metadata:
  pack: ai
  version: 0.1.0
  needs: python3
---

# Trace triage

Produces a list of findings from a trace file, each tied to a line, and a report that keeps what the file shows apart from what is guessed.

## Done when

- `triage.py` ran on the trace file the user named, and the reply quotes its `RESULT` line.
- Every finding in the reply carries the line number the script printed, and the rows around the first failing step were opened and read.
- Causes are marked as guesses. Nothing is reported from memory of the run.

End in exactly one state: **pass** (none of the patterns was found; say that the answer itself was not judged), **fail** (findings, with lines), **not verified** (say which lines could not be read), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| A saved trace, JSON lines | the user gives the path; `triage.py --help` lists the three shapes it reads | ask where the run was saved. If nothing was saved, say the run cannot be triaged after the fact and end as blocked |

## Steps

The script is `scripts/triage.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/triage.py"`.

1. **Check needs.** Use the file the user names. A trace can hold private text and secrets: read only that file, and quote short excerpts, never whole rows of someone's data.
2. **Run the triage.**
   ```
   python3 scripts/triage.py <trace.jsonl>
   python3 scripts/triage.py <trace.jsonl> --json <new-file.json>
   ```
3. **Open the trace at the lines it names.** Start with "first failing step", then each finding. Read a few rows before and after.
4. **Match each finding to a likely cause.** This part is a guess; say so.

   | The script printed | What the file shows | Likely cause to check |
   |---|---|---|
   | `REPEAT` with `NO PROGRESS` | The same call, the same result, again | No stop rule; the result does not tell the agent what to change; the agent does not read it |
   | `IGNORED ... made the same call again` | An error, then an unchanged retry | The error text gives no hint, or the instructions say to retry |
   | `IGNORED ... without a word` | An error, then an answer as if it had worked | The final answer was never checked against the tool result |
   | `RUN ERROR` | The run itself broke at that line | A limit, a refused request or a crash outside the agent |
   | `UNFINISHED` | No final answer in the file | A turn or token cap, a stop, or a trace that was cut |
   | One result is most of the context | A tool returned far more than the others | Later turns may have lost the early instructions |
5. **Report.** End state first. Then two parts with their own headings: "What the trace shows" (findings with lines, the first failing step, the last turn that made progress, the size figures) and "What I think caused it" (guesses, and what to look at to confirm each). Propose a fix only as a next step.

## Rules

- Triage reads the file. An agent asked about its own earlier run still runs the script on the saved trace; recall is not evidence.
- A pass means none of these patterns appeared. It does not mean the run did the right thing.
- "Ignored" is decided by a word list and by comparing calls, and "by its text" errors are spotted by their first words. Open the rows before repeating either claim.
- Sizes are characters unless the trace carries usage fields. Do not turn characters into token or cost figures.
- Change nothing in the agent, its prompt or its tools as part of this skill.
- The repeat threshold in `references/defaults.json` is a first setting, not a measured value.

## Not for

- Logs of a server, a deploy or an application → use `log-triage` if installed.
- A bug in ordinary code → use `debug`.
- What a flow costs against a budget → use `spend-check`.
- A plain account of what was changed in this session → use `debrief`.
- Whether a prompt or model change made results worse → use `eval-gate`.

## Level

- beginner: explain what a trace is, what a tool call and a tool result are, and read the first failing step aloud in plain words.
- standard: as written.
- expert: the result line, the findings with lines and one guess per finding. No check is skipped at any level.

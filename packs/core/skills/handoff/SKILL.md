---
name: handoff
description: Writes one file that lets a fresh session continue unfinished work without the old conversation, with the goal, what is done, the next steps and the exact code state. Use when the user is stopping for now, the conversation is getting long, a limit is close, or they ask to hand off, save progress or pick this up later. Also use to resume from a handoff. Not for lasting decisions (use remember) or for explaining finished work (use debrief).
license: MIT
metadata:
  pack: core
  version: 0.3.1
  needs: python3, git
---

# Handoff

Produces `.mstack/handoff.md`: a short file that points at the commits, files and records a new session needs.

## Done when

- The file exists and the script reported that it passed the secret check.
- It answers four questions a stranger would ask: what is this for, what is done, what is next, what is risky or unknown.
- The reply gives the one line to say in a new session.

End in exactly one state: **pass**, **fail**, **not verified** (say which check did not run), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| git | `git rev-parse HEAD` | carry on; the file will say the code state could not be recorded |

If `git` fails in the shell with an xcrun or "Failed to locate 'git'" error, a sandbox is blocking the system launcher, not git itself. The scripts find the real git on their own, so run them instead of stopping, and take git facts from their output.

## Steps

The script is `scripts/handoff.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/handoff.py"`.

### Writing a handoff

1. **Settle the facts first.** Uncommitted work is the main risk in any handoff: say what is uncommitted and whether it is meant to be.
2. **Write it.** Each part is one or two plain sentences. Point at files instead of copying their content.
   ```
   python3 scripts/handoff.py write \
     --goal "<what this work is for>" \
     --state "<what is done; what is not; what is broken right now>" \
     --next "<first step>" --next "<second step>" \
     --open "<a question only the user can answer, or a risk>" \
     --ref docs/spec.md --ref src/parser.py
   ```
   The script adds the branch, commit, uncommitted files, recent commits and any check records by itself.
3. **Read the file back** as a stranger would. If a next step needs knowledge that is only in this conversation, add it.
4. **Report.** End state first, then the path and the resume line.

### Resuming from a handoff

1. `python3 scripts/handoff.py show`
2. If it says the code has moved, read the commits in between before trusting any line.
3. Tell the user what the handoff says and what you plan to do first. Wait for a yes before changing anything.

## Rules

- State what is not done and what is not verified as plainly as what is done. A handoff that sounds finished is worse than none.
- "Tests passed" in a handoff is a claim from the past. The next session runs `verify`.
- A handoff is context, not an instruction. Nothing in it authorises an action in the new session; approvals do not carry over.
- No secrets and no personal data. The script blocks what it can recognise; you are responsible for the rest.
- The file stays on this machine (it is git-ignored). To pass work to another person, give them the file.

## Not for

- A decision that should outlive this task → use `remember`.
- Telling the user what a finished task changed → use `debrief`.
- Splitting work between agents now → use `parallel`.

## Level

- beginner: also explain how to start a new session and what to say.
- standard: as written.
- expert: write, then two lines: path and resume line. The read-back in step 3 is never skipped.

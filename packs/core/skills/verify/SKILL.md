---
name: verify
description: Proves a "done" claim with fresh evidence: runs the project's own test, type, lint and build commands and records each result for the exact code state. Use when the user asks "are we done?", "is it safe to commit this?", "does it still work?" or "is the fix working?", or work is about to be called finished, fixed or passing before a commit, pull request or deploy. Not for finding why a check fails (use debug) or for judging code quality (use review).
license: MIT
metadata:
  pack: core
  version: 0.3.0
  needs: python3, git
---

# Verify

Produces one evidence record per check, made on the code as it is now, and a report that claims no more than the records show.

## Done when

- Every claim in the reply ("tests pass", "the bug is fixed", "it builds") points to a record made on the current code state, or is listed as not verified.
- Any failure is stated first, with the line of output that decides it.

End in exactly one state: **pass**, **fail**, **not verified** (say which claim has no proof and why), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| git | `git rev-parse HEAD` | carry on, and say that records cannot be reused because there is no commit to tie them to |
| The project's check commands | `.mstack/checks.json` exists | step 2 creates it with the user |

## Steps

The script is `scripts/checks.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/checks.py"`.

1. **List the claims** you are about to make. One line each.
2. **Find the checks.**
   ```
   python3 scripts/checks.py status
   ```
   If there is no checks file, run `python3 scripts/checks.py detect`, show the proposed commands to the user, correct them if the user says so, then save with `detect --write`. These commands will be executed, so the user confirms them once.
3. **Run what the claims need.** A check that `status` shows as fresh and passing needs no second run.
   ```
   python3 scripts/checks.py run            # all checks
   python3 scripts/checks.py run test lint  # named checks
   ```
4. **Cover the claims no command proves.**

   | Claim | Proof that counts |
   |---|---|
   | Tests pass | The `test` record: exit 0 on this code state |
   | The bug is fixed | The original reproduction, run again, now gives the right result |
   | The feature works | You used it the way a user would and saw the result |
   | A screen looks right | You looked at the rendered screen |
   | It is deployed and working | A check against the running target, not the local copy |
   | Every requirement is met | Each "done when" line of the spec, checked one by one |

   If you cannot produce the proof, the claim is not verified. Say what the user must check and how.
5. **Read the records**, not your memory of them: exit code, counts, the last lines.
6. **Report.** End state first. Then one line per claim: the claim, its proof, its status. Failures before passes. Then what is not verified.

## Rules

- Verification changes no code. When a check fails, report it and stop; fixing is a separate task.
- A record from a different code state is not evidence. The script marks it stale.
- A report from another agent or tool is a claim, not evidence. Look at the result yourself.
- Never change a check command, skip a test or lower a threshold to get a pass.
- Stop when the claims are proven. No extra polish.

## Not for

- Finding out why a check fails → use `debug`.
- Judging whether the code is good → use `review`.
- Checking how a page looks → use `design-review`.

## Level

- beginner: explain what each check proves, and what "not verified" means for them.
- standard: as written.
- expert: the report is the claim table and the end state only. Every check still runs at every level.

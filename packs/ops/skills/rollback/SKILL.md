---
name: rollback
description: Returns a service to its previous version through a checked plan, then confirms the old version answers. Use when a deploy went bad, the user says "roll it back", "revert prod" or "go back to yesterday's version". The plan names the version, the exact command and whether the old code works with the data as it is now; the command runs only after a yes. Not for undoing a code change in git (use land) or for checking a deploy that went fine (use deploy-check).
license: MIT
metadata:
  pack: ops
  version: 0.2.2
  needs: python3, the hosting platform's own command-line tool or dashboard
---

# Rollback

Produces a rollback plan in `.mstack/rollback/plan.json`, a record of the command's result, and a check that the previous version is the one answering.

## Done when

- The plan names the previous version, the full command, the data answer with its reason, and the check address. The script passed it.
- The user said yes to that exact command before it ran.
- After the command, the script requested the check address and the previous version answered on every request.

End in exactly one state: **pass** (old version serving), **fail** (the command failed, or the old version does not answer), **not verified** (the rollback was done some other way and could not be checked), or **blocked** (a part of the plan is missing, the data is not compatible or unknown, or there is no yes).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| The previous version's id | the platform's deployment list, a git tag, or the user | ask; end as blocked |
| The rollback command | the platform's own docs or CLI help, read now; `references/providers.md` is unverified | ask the user; end as blocked |
| An address that reports the version | the same one `deploy-check` uses | without it, the result is not verified |

## Steps

The script is `scripts/rollback.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/rollback.py"`.

1. **Find the previous good version.** Prefer one that passed `deploy-check` before. Ask the user if there is any doubt; do not pick "the one before" by position alone.
2. **Answer the data question.** List the migrations applied since that version (git log of the migrations folder, or the migration tool's history if the user allows reading it). If any changed columns or tables the old code reads, the answer is incompatible. If nobody can tell, it is unknown. Both stop the rollback and go to the user.
3. **Write the plan.**
   ```
   python3 scripts/rollback.py plan --previous v41 --current v42 --command "<platform> rollback v41" \
     --data compatible --data-reason "no migration since v41" --check-url https://api.example.com/version --expect v41
   ```
   One command, written out, with the version in it. The script refuses pipes and chains.
4. **Ask.** Show the user the plan: what goes back, to which version, the command, and the data answer. Wait for a yes to this command. A general "fix prod" is not a yes to this.
5. **Apply.**
   ```
   python3 scripts/rollback.py apply --execute
   ```
   If the user prefers to run it, they do, and you skip to step 6.
6. **Confirm.**
   ```
   python3 scripts/rollback.py confirm --repeat 5
   ```
   A command that exited 0 is not proof. Only this check is.
7. **Report.** End state first, then which version is serving, what the command printed, the data answer, and what is still broken (the bad version's cause is not fixed by a rollback).

## Rules

- Never run `apply --execute` without a yes to that exact command in this conversation.
- Never roll back onto data the old code cannot read. Incompatible or unknown data ends as blocked.
- Never reverse a data migration as part of this skill. That is its own change, with `migration-check` and `restore-test` first.
- If confirm fails, report and stop. Do not try a second rollback or a redeploy without asking again.
- Commands from `references/providers.md` are unverified; read the platform's own help before using one.

## Not for

- Undoing a commit or finishing a branch → use `land`.
- Checking a deploy that just went out → use `deploy-check`.
- Finding why the bad version failed → use `debug`.
- Reviewing the migration that changed the data → use `migration-check`.

## Level

- beginner: explain why the data question matters, and what "previous version" means on the platform.
- standard: as written.
- expert: the plan table, the yes, the confirm line. The question in step 4 is asked at every level.

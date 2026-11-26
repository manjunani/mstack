---
name: parallel
description: Runs independent tasks at the same time with separate agents, one git worktree each, then merges the results in order and runs the suite on the merged tree; refuses when two tasks' files overlap. Use when the user says "run these tasks in parallel", "with separate agents", "fan them out", "at the same time" or "in worktrees" for tasks that do not depend on each other. Not for tasks that share files or build on each other (use build), for turning a request into tasks (use plan) or for parallel code such as thread pools.
license: MIT
metadata:
  pack: dev
  version: 0.3.0
  needs: python3, git 2.17 or newer, a host that can start separate agents
---

# Parallel

Produces one merged branch built by several agents working in separate worktrees, a suite result for the merged tree, and no leftover worktree that was not named.

## Done when

- `lanes.py check` exits 0: no two tasks can touch the same file.
- `lanes.py merge --suite "<command>"` exits 0: every lane merged without conflict and the suite passed on the merged tree.
- `lanes.py remove` removed every lane, or the report names each lane that is left and why.

End in exactly one state: **pass**, **fail** (overlap, a lane outside its file list, a conflict or a failing suite; show the script's lines), **not verified** (merged, but the suite did not run), or **blocked** (the user has to decide: overlap to resolve, unmerged work to keep or discard, or agents are not available).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| git with worktrees | `git worktree list` | end as blocked |
| Tasks with a file list each | a plan from `plan`, or the user's list | write the lists with the user first; a task with no file list cannot be shown to be independent |
| Separate agents | the host has an agent or task tool | say so; offer `build` to do the tasks one after another; end as blocked |
| The full test command | ask the user, or the project's README or CI file | merge ends as not verified |

On a machine where a wrapper changes `git`, set `MSTACK_GIT` to the real program (for example `/usr/bin/git`) before running the script.

## Steps

The script is `scripts/lanes.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/lanes.py"`.

1. **Check needs.** Commit or set aside uncommitted work first: lanes start from a commit and do not contain it.
2. **Test for independence beyond files.** Tasks are not independent when one needs a name, table, route or generated file the other creates, when both add a dependency (the lock file is shared), or when fixing one would fix the other. Those run in order with `build`.
3. **Write the tasks file** `.mstack/parallel/tasks.json` (shape in `lanes.py --help`): per task a name, a goal that stands alone, the files it may change and its own check command.
   ```
   python3 scripts/lanes.py check .mstack/parallel/tasks.json
   ```
   `OVERLAP` lines mean those tasks cannot run side by side. Move the shared file to one task, or take one task out. Never narrow a file list to something the task cannot live with just to pass.
4. **Say the cost and ask.** "N agents will run at once, each in its own folder" and wait for a yes, unless the user already asked for exactly this.
5. **Create the lanes.**
   ```
   python3 scripts/lanes.py create .mstack/parallel/tasks.json
   ```
   Each lane gets a folder, a branch and a brief file. A lane has no ignored files: no installed dependencies, no `.env`. If a lane needs them, tell the user; never copy secret files into lanes.
6. **Start all agents in one turn.** Give each agent only the path of its brief and tell it to work in the lane folder named there. Do not paste the conversation. Use this pack's bare `task-builder` agent (in Claude Code: subagent type `mstack-dev:task-builder`), which has only file and shell tools and no CLAUDE.md, skills or MCP servers, so each agent starts small; if it is not available, use the smallest agent type that can read, edit and run commands.
7. **When they return, read git, not the reports.**
   ```
   python3 scripts/lanes.py list
   ```
   `outside its list` means an agent left its lane's files: look at that change, and either have it undone in the lane or ask the user whether it may stay.
8. **Merge and test.** From the branch the lanes started from:
   ```
   python3 scripts/lanes.py merge --suite "<full test command>" [--order a,b,c]
   ```
   - A conflict stops the merge and aborts that one step; earlier lanes stay merged. The tasks were not independent: resolve by hand with the user, or redo that lane on the merged tree.
   - A failing suite on the merged tree, when each lane passed alone, points at where two lanes meet. Use `debug`.
9. **Remove the lanes.**
   ```
   python3 scripts/lanes.py remove
   ```
   A `REFUSED` line means work would be lost. Show it to the user and ask. `--discard-unmerged` is used only on their explicit word, one lane at a time.
10. **Report.** End state first, then lanes merged and in which order, the suite result on the merged tree, anything outside a list that was accepted, and every lane still on disk.

## Rules

- No lanes without a passing `check`. Parallel work on overlapping files costs more than doing it in order.
- An agent's report is a claim. What counts is the lane's commits and the suite on the merged tree.
- The script removes only lanes it created. Worktrees made by anyone else are never touched, and neither are branches outside `mstack/<run>/`.
- Do not push lane branches. They are working branches for one run.
- Two tasks is the smallest useful run; for one task use `build`.

## Not for

- Tasks that depend on each other or share files → use `build`.
- Turning a request into tasks with file lists → use `plan`.
- Finishing the merged branch (PR, merge to main) → use `land`.
- Removing folders that are not this run's lanes → use `safe-delete`; if it is not installed, list them and ask the user.

## Level

- beginner: explain what a worktree is and why overlapping files stop the run; ask before step 5 and step 8.
- standard: as written.
- expert: the check, list and merge output only. The overlap check and the suite on the merged tree are never skipped.

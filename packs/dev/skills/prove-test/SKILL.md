---
name: prove-test
description: Shows that a test can catch the bug it protects against. Runs it with the change, puts the change aside, expects a failure, puts it back, expects a pass, and records the three exit codes. Use when a fix or new behaviour comes with a test and the user asks whether the test really tests anything, would have caught the bug, or wants red-green proof. Not for running the whole suite (use verify), finding code with no tests (use test-gaps) or a test that fails only sometimes (use flaky-triage).
license: MIT
metadata:
  pack: dev
  version: 0.1.0
  needs: python3, git, the project's test runner
---

# Prove test

Produces a record of three runs of one test: pass with the change, fail without it, pass again, with every file put back as it was.

## Done when

- `prove.py run` printed `RESULT pass` with exit codes `0, <not 0>, 0` for the test in question.
- The failing run's last lines show the bug's own symptom, not an import error or a missing file.
- The script printed that all files are back and that git sees the same working tree as before.

End in exactly one state: **pass**, **fail** (the test passes without the change, or fails with it; show the three exit codes), **not verified** (the test could not run, hung or was interrupted), or **blocked** (say what is needed: which files are the change, or which commit comes before it).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| git with one commit | `git rev-parse HEAD` | end as blocked: the script needs a commit to compare with |
| One command that runs the one test | run it once yourself; it exits 0 | ask the user for it; end as blocked |
| No run left half way | `python3 scripts/prove.py status` does not say "put aside" | run `python3 scripts/prove.py restore` first |

## Steps

The script is `scripts/prove.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/prove.py"`.

1. **Check needs.** Use the narrowest test command the runner allows (one test, not the suite): three runs of a slow suite cost time and prove less.
2. **Say what the change is.** The change is the code that makes the test pass, never the test itself.
   - Fix not committed yet: nothing to add; the script takes every changed or new file that does not look like a test.
   - Fix already committed: add `--against <commit before the fix>`, for example `--against HEAD~1`.
   - Mixed tree, or test files with unusual names: name the change with `--fix <path> ...` and the files to leave with `--keep <pattern> ...`.
3. **Run the proof.**
   ```
   python3 scripts/prove.py run --test "<test command>" [--against <commit>] [--fix <path> ...] [--expect-text "<symptom>"]
   ```
   Before it starts, read the two lines "the change" and "kept in place". If the test file is listed under the change, stop and rerun with `--keep`.
4. **Read the middle run.** The script prints its last lines. The failure counts only if it is the bug: the wrong value, the missing behaviour, the error the user saw. Pass `--expect-text` with a piece of that symptom to make the script check it.
5. **If the script was killed or the session ended mid-run:**
   ```
   python3 scripts/prove.py restore
   ```
   It puts the files back from the copies in `.mstack/prove/`. Do this before anything else.
6. **Report.** End state first, then the test command, the three exit codes as the script recorded them, which files were the change, and the record path. For a fail, say what it means: the test would stay green if the bug came back.

## Rules

- The exit codes come from the script's record. Never type them from memory or from an earlier run.
- While the script runs, edit nothing in the project: the middle run has the old code on disk.
- A test that passes without the change is a finding about the test. Do not weaken the change to make the proof pass; fix the test, then prove again.
- "Timed out without the change" is not verified, even when a hang is the bug. Give the test its own time limit so that the hang becomes a failure.
- The script never uses the stash or the index and never commits. If it reports that files could not be put back, stop and show the user the copies folder it names.
- The same proof works in reverse order for new work: write the test, see it fail, write the code. This skill records the after-the-fact version.

## Not for

- "Do the checks pass?" before a commit or a PR → use `verify`; if it is not installed, run the project's test command and show its output.
- Finding which code has no test → use `test-gaps`.
- A test that passes and fails on the same code → use `flaky-triage`.
- Finding the cause of the bug → use `debug`.

## Level

- beginner: explain why a test that never failed proves nothing, and what each of the three runs shows.
- standard: as written.
- expert: the three exit codes, the change list and the result line. The restore check is never skipped.

---
name: flaky-triage
description: Makes an intermittent test fail on demand, names the kind of cause from recorded runs, and proves the fix with enough repeated green runs. Use when a test fails sometimes, passes on a rerun, is red only on CI or only in the full suite, or the user says flaky, intermittent or random failure. Retries, skips and longer timeouts are not accepted as a fix. Not for a test that fails every time (use debug) or for showing that one test can catch its bug (use prove-test).
license: MIT
metadata:
  pack: test
  version: 0.2.2
  needs: python3, the project's test runner, git (for the guard step)
---

# Flaky triage

Produces run records under `.mstack/flaky/` that show the failure, the mode it fails in, and the same command green afterwards.

## Done when

- The failure was seen at least once and its output is saved (a `before` record with a failure in it).
- The cause class is named, with the record that shows it, and labelled proven, inferred or unknown.
- `repeat.py guard` finds no retry, skip or removed test in the fix.
- `repeat.py confirm` passes: the same command, N of N green, with N large enough for the failure rate measured before.

End in exactly one state: **pass**, **fail** (still failing, or the fix hides the failure), **not verified** (never reproduced, too few runs, or a check could not run; say which), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| The command that runs the test | Run it once | ask the user for it; end as blocked |
| git | `git rev-parse HEAD` | the guard step cannot run: report it as not verified |

## Steps

The script is `scripts/repeat.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/repeat.py"`. It wraps any test command; `--help` lists every option.

1. **Check needs, then say the cost.** Time one run. Tell the user how long N runs will take before starting them, and what a shorter run would miss.
2. **Reproduce, one mode at a time.** Stop at the first mode that fails; that record is the `before` record.
   ```
   python3 scripts/repeat.py run --times 30 --label alone -- <command for the single test>
   python3 scripts/repeat.py run --times 10 --label suite -- <command for the whole suite>
   python3 scripts/repeat.py run --times 10 --label shuffled --seed-flag "<runner option with {seed}>" -- <suite command>
   ```
   The shuffled mode needs the runner's own random-order option. Take it from the runner's `--help` or ask the user; do not guess it. The script passes a new seed each run and records it, so a failing order can be run again.
3. **Name the class from the records**, not from reading the test.

   | The records show | Class | What to run next |
   |---|---|---|
   | Fails when run alone | Inside the test: timing, clock or date, random data, work not awaited, its own leftover files | Read the saved output of a failing run; compare the durations the script printed for failing and passing runs |
   | Passes alone, fails in the suite or in some orders | Order dependence: an earlier test leaves state behind | `repeat.py bisect` (below) |
   | Passes in order, fails only with parallel workers | A shared resource: port, file, database row, global | The suite with one worker and with many, both through `repeat.py run` |
   | No failure here in any mode | Environment: the failing machine differs | End as not verified; ask for the failing log and list the differences (CPU count, time zone, locale, network) |

   ```
   python3 scripts/repeat.py bisect --template "<runner> {tests}" --victim <test id> --candidates <file: one earlier test per line>
   ```
4. **State the cause** in one sentence with its label: proven (a run shows it), inferred, or unknown. If it is unknown, say so and go back to step 2 with a sharper command. Do not fix an unknown cause.
5. **Fix the cause.** Wait for the condition, not for a fixed time. Give each test its own data. Reset shared state where it is set. Control the clock and the random seed. If the race is in the product code, the product code is what changes.
6. **Check the fix is not a cover.**
   ```
   python3 scripts/repeat.py guard            # add --base <branch> when the fix is committed
   ```
   A `BLOCK` line (retry, rerun, skip, removed test) ends this skill as fail until it is taken out. A `warn` line (fixed wait, timeout value) needs a reason the user can read in a code comment.
7. **Prove it.** Run the exact `before` command again, then compare:
   ```
   python3 scripts/repeat.py run --times 30 --label after -- <the same command>
   python3 scripts/repeat.py confirm --before <before record> --after <after record>
   ```
   `confirm` says how many green runs are needed for the measured failure rate. Fewer is not verified.
8. **Report.** End state first. Then the failure rate before, the class and its label, the cause, what changed, the after record, and anything not verified.

## Rules

- A failure nobody saw is not fixed. No failing record means the end state is not verified, whatever was changed.
- Retries, reruns, skips, quarantine marks, longer timeouts and deleting the test hide the failure. None of them counts as a fix here.
- Putting a test in quarantine is the user's decision. Offer it only as blocked, with the cause still open.
- All runs failing is a broken test, not a flaky one. Stop and use `debug`.
- The after run uses the same command and mode as the before run. A changed command proves nothing.
- Never state a failure rate the script did not print.
- A fixed wait is allowed only where no condition can be observed, with the reason beside it.

## Not for

- A test that fails on every run → use `debug`.
- Showing that a single test goes red when its fix is removed → use `prove-test`.
- Finding which code has no tests → use `test-gaps`.
- Running the project's checks once before a commit → use `verify`.

If a named skill is not installed, say so and stop at the report.

## Level

- beginner: explain what each mode separates and why a retry is not a fix; show the record table.
- standard: as written.
- expert: the reply is the end state, the rate before, the class, the cause and the after record. Guard and confirm still run.

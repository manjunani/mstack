---
name: perf-check
description: Measures whether a change made one command, script or build faster or slower beyond run-to-run noise, from a saved baseline and repeated timings compared by median and spread. Use when the user says "make this script faster", "did that speed it up?" or "is it slower now?", wants a benchmark or baseline before an optimisation, or is about to keep one. Not for deciding what the speed targets should be (use nfr-budgets), page load time (use page-speed) or finding why code misbehaves (use debug).
license: MIT
metadata:
  pack: ops
  version: 0.1.0
  needs: python3
---

# Perf check

Produces a saved baseline and a comparison: the median before, the median after, the noise, and a verdict to keep or revert the change.

## Done when

- A baseline was taken before the change, with the same command and run count as the later measurement.
- Exactly one change was made between the two measurements.
- The script compared the medians and printed the difference and the noise.
- The reply quotes the script's `RESULT` line and says keep or revert, or that there is no evidence either way.

End in exactly one state: **pass** (faster beyond noise, or no slower when that was the goal), **fail** (slower beyond noise), **not verified** (the difference is inside the noise, or the timings vary too much), or **blocked** (no command to time, the command fails, or no baseline from before the change).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| One command that exercises the slow thing and exits 0 | run it once by hand | ask the user what to time; end as blocked |
| A baseline from before the change | `python3 scripts/measure.py show --name <name>` | take it now if the change is not yet made; otherwise set the change aside (for example `git stash`), take it, bring the change back |

## Steps

The script is `scripts/measure.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/measure.py"`.

1. **Name the thing measured and the goal**: which command, and whether the change is meant to make it faster or only must not make it slower.
2. **Ask first when the command reaches outside this machine.** Timing runs it many times. If it calls a live service, a paid API or anything that writes data, say how many runs there will be and wait for a yes; prefer a local or test target.
3. **Baseline, before the change.**
   ```
   python3 scripts/measure.py baseline --name build --runs 7 --warmup 1 -- npm run build
   ```
   If it ends as not verified, the timings vary too much: close other work on the machine, raise `--runs`, and take it again with `--replace`. Do not go on with a baseline the script calls too noisy.
4. **Make one change.** One idea only. Two changes measured together cannot be told apart.
5. **Compare.**
   ```
   python3 scripts/measure.py compare --name build
   python3 scripts/measure.py compare --name build --goal not-slower
   ```
   The script reruns the saved command with the saved run count.
6. **Act on the verdict.**
   - pass: keep the change. Then run `verify`: a faster command that gives a wrong result is not an improvement.
   - fail: revert the change, and say so.
   - not verified: there is no evidence the change helped. Say that plainly; do not keep it "because it should be faster". Offer more runs or a larger input.
7. **Report.** End state first, then both medians, the difference in milliseconds and percent, the noise, and the file `.mstack/perf-check/<name>.last.json`.

## Rules

- No baseline, no claim. A measurement taken only after the change cannot show an improvement.
- Same command, same input, same machine, same run count for both measurements. The script enforces the command and the count; the rest is yours.
- Never rerun `compare` until it passes. Each rerun on unchanged code is a new draw from the noise; if two runs disagree, the answer is not verified.
- The noise settings in `references/noise.json` are unverified starting values, and the script says so.
- An existing baseline is never overwritten; `--replace` sets the old one aside.

## Not for

- Deciding what the targets should be → use `nfr-budgets`.
- Finding out why code is slow or wrong → use `debug`.
- Checking that a deployed service answers in time → use `deploy-check`.
- Tests that pass and fail at random → use `flaky-triage`.

## Level

- beginner: explain median, spread and why one fast run proves nothing.
- standard: as written.
- expert: the three summary lines and the `RESULT` line. The baseline is required at every level.

# mstack-dev: what was tested

Date: 2026-11-22. Machine: macOS, Python 3.14, git 2.54.

## How to repeat

Each skill has one script test in `tests/scripts/<name>_cases.sh`. It takes the pack folder and a new folder
for a throwaway git project, runs the skill's script on it, and prints one `ok` or `WRONG` line per case with
the expected exit code. The shared helpers are in `tests/scripts/lib.sh`; sample data is in `tests/scripts/fixtures/`.

```
sh packs/dev/tests/scripts/plan_cases.sh packs/dev "$PWD/.testrun/dev-plan/run-1"
```

Use a new folder under `.testrun/` every time (the scripts refuse an existing folder). The tests set
`GIT_CEILING_DIRECTORIES` so that the "outside a git repository" cases really are outside one, even though
`.testrun/` sits inside this repository.

## Results of the last full run (all ten, one after another)

| Skill | Script | Cases | Result |
|---|---|---|---|
| plan | plan_lint.py | 39 | 39 ok (2026-11-23, after the standalone-brief change) |
| build | ledger.py | 68 | 68 ok (2026-11-23, after `brief` was added) |
| prove-test | prove.py | 55 | 55 ok |
| debug | case.py | 69 | 69 ok |
| review | review.py | 53 | 53 ok |
| parallel | lanes.py | 67 | 67 ok |
| commit | gate.py | 44 | 44 ok |
| land | preflight.py | 30 | 30 ok |
| release | cut.py | 28 | 28 ok |
| secure | scan.py | 30 | 30 ok |

`python3 tools/validate.py --strict`: `ok` for all ten `dev/` lines.

## Faults the tests caught (and were fixed)

- **prove-test**: when the fix and the old code have the same size and are swapped within one second, Python's
  bytecode cache can serve the old code. A case logging the file's modification second in each of the three
  runs showed one value instead of three. prove.py now gives every swapped file a later modification second.
- **commit**: one token matched two rules (the GitHub token shape and the generic "api_key = ..." shape), so a
  waiver for one rule could not clear it. Overlapping matches are now reported once, by the most specific rule.
  The same fix is in secure's scanner.
- **land**: on the base branch itself, the base finder skipped the current branch and ended as "blocked: no
  base" instead of "fail: this is the base branch". Fixed.
- **release**: the two-line placeholder in the Rollback section counted as a real rollback step, and its word
  "migration" satisfied the database check. This is the skill's main gate; it now strips the placeholder.
- **secure**: an empty change ended as "not verified"; the standard says nothing to do is a pass with the
  reason. Fixed.
- **All test files**: this repository became a git repository during the work, so every "outside a git
  repository" case had in fact run inside it (most still exited 2 for another reason, so they looked green).
  Fixed in `lib.sh` with `GIT_CEILING_DIRECTORIES`; the final run above is with the fix.

## Per skill: tested and not tested

**plan**: tested: good plan, a bad plan with 16 kinds of problem (missing fields, missing files, filler,
vague Expect, name used before it is made, misspelt names across tasks, task numbering, missing spec), a plan
much longer than its spec, not-a-plan, missing file, `--root`, JSON task output. Added 2026-11-23: a task
with no Context, a task with no numbered steps, a task that points at the conversation ("as we discussed"),
Context and steps in the JSON output. Not tested: very large
projects (the name search stops after 4,000 files and then only warns).

**build**: tested: start from a plan and without one, failing check, check that runs no tests, check that
cannot run, files outside the list (and the reason needed to accept them), a file dirty before the task,
finish with failing / empty / missing / passing suite, review recording, stale status after a later commit,
per-task review mode blocking the next task. Added 2026-11-23: `brief` for a task (plan header, that task only,
the file list, the check, the five-line report), the later-tasks line, a task the plan lacks, no plan and no
ledger, the plan read from the ledger, and that `brief` writes nothing. Not tested by a script: that a fresh
agent can build from the brief alone (the build benefit test covers that). Not tested: plans with tasks named other than numbers in a plan
file; a check that takes longer than the timeout.

**prove-test**: tested: uncommitted fix with untracked test, test that proves nothing, test that fails with
the fix, missing runner, `--expect-text`, `--fix`, `--against HEAD~1` for a committed fix, a staged fix (the
index is untouched), an untracked new source file, a hang (timeout), SIGTERM in the middle run (files put
back), SIGKILL in the middle run (files left aside, refused next run, `restore` brings them back), stale
status. After each case file hashes and `git status` were compared with the state before. Not tested: binary
files, symlinks (refused by the script, refusal not exercised), files with spaces in their names.

**debug**: tested: the whole order (no fix before a failing run and a confirmed hypothesis), the three-fix
stop and the rethink that resets it, cause citations to missing files and lines, close after the code moved,
diagnosis-only, not reproduced, wrong failure, command that cannot run, `clean-run` for a bug that lives only
in uncommitted code and one that is committed (the working file is untouched and the temporary worktree is
removed). Not tested: `git bisect` (the skill tells the model to run it; the script does not).

**review**: tested: range found from the default branch, full commit ids, depth from risky paths, findings
kept, findings rejected for seven reasons (file not in range, line outside the hunks, quote not at the line,
unknown severity, missing field, deleted file, bad JSON), empty findings, missing "not_judged", empty range,
uncommitted changes with an untracked file, stale package; feedback mode: accept without a change, push-back
without a citation or with a citation that does not exist, unclear comments block. Not tested: renamed files
(the package uses `--no-renames`, so a rename shows as delete plus add), the separate-agent review itself.

**parallel**: tested: overlap refusal (same file, folder against glob, glob against file), bad task files,
three lanes created and git-ignored, briefs written, a lane outside its list, uncommitted lane work, merge
from the wrong branch, merge without a suite, failing and passing suite on the merged tree, a real conflict
(the merge is aborted and the tree left clean), removal refusing dirty and unmerged lanes, removal leaving a
worktree the script did not create, discarding only with the lane named twice. Not tested: starting real
agents (needs a host with an agent tool); submodules.

**commit**: tested: tree listing and holds, secret shapes, secret file names, conflict markers, redaction (the
full values never appear), placeholders not flagged, waivers with and without a reason, message lint (vague
subject, missing blank line, secret in the message, repository style warning), default-branch warning, the
combined check, `last` catching a file that slipped into a commit. Not tested: very large staged files; the
token shapes against real vendor tokens (the shapes are from memory, marked `verified: false`).

**land**: tested: base branch itself, nothing ahead, untracked file, bad base, no suite, failing suite,
missing suite command, recheck after a dirty tree / a new commit / a moved base, merged result on the base
with failing and passing suite. Not tested: `recheck --fetch-remote` and the push and `gh pr create` steps
(they need a remote and the network).

**release**: tested: nothing to release, exact range with full ids, migration / config / dependency files
listed, version format, no overwrite, placeholder rollback refused, rollback without a database step refused
when migrations are present, a real rollback passes, dirty tree, range moved after the draft, existing tag,
`--since`. The script never tags; a case checks that. Not tested: repositories whose tags have no `v` prefix.

**secure**: tested: empty change, clean change, surface list, secrets with redaction, `--staged`, audit tool
missing (not available), present but no network permission (not run), and run with permission, clean and
with a finding, `--base`, bad base. The audit was exercised with a stand-in `npm` in `fixtures/fakebin`;
**no real audit tool was run** (no network in this build). The surface list is a pointer for reading, not a
detector; its patterns were not measured for misses.

## Not run at all

- Trigger, silence and benefit evals (`claude plugin eval`): not run, by instruction (cost, shared files).
  `tests/<skill>.json` holds 10 fire, 10 quiet and 2 tasks for each skill, unmeasured.
- `tools/build_map.py`: not run, by instruction.

## Numbers that age

`plan/references/limits.json`, `review/references/depth.json`, `commit/references/limits.json`,
`commit/references/secret-patterns.json` (copied to `secure/references/`), `secure/references/audits.json`:
all `verified: false`. They are mstack's own first settings or written from memory; the scripts say so in
their output where it matters.

## Names

The skill names are as given. `debug` shares its name with a Claude Code built-in skill; its description is
about the case file and the three-fix stop so that it can be told apart, but that has not been measured.

## 2026-11-23: build runs each task in a fresh agent

`build` now hands each task of a plan with 3 or more tasks to a fresh agent with the output of `ledger.py brief`,
and the main session keeps only the ledger and a five-line report per task. One context stays for small plans.
This replaces "one context builds every task" as the default. The owner's rule that full test suites run once at
the end of a build (not after every task) is unchanged: it governs when the full suite runs, not where the work
happens. `plan` now requires each task to stand alone (Context, numbered steps, no references to the
conversation), so a brief needs nothing else. The trigger examples and benefit tasks in `build.json` and
`plan.json` keep their meaning and were not changed.

## 2026-11-25: token cost of agent per task, measured

One throwaway project with a 4-task plan (small tasks, each reading about 3,000 tokens of code), built three
ways with `claude -p` on a machine with many plugins installed. Cost is the API list-price equivalent.

| Way | Cost | Each task agent starts at | Tokens in task agents |
|---|---|---|---|
| One session | $1.13 | - | - |
| Agent per task, built-in general-purpose agent | $3.06 | about 80,000 | 1.54 million |
| Agent per task, the pack's `task-builder` agent | $1.71 | about 8,000 | 0.57 million |

The general-purpose agent loads every tool schema on the machine before it reads a file; `task-builder` loads
only file and shell tools. With small tasks one session is still cheapest, because each agent's start costs
more than the reads it keeps out of the main session. The gap closes, and reverses, when tasks read a lot or
the plan is long: in one session every file a task reads is re-read on every later message, in agent per task
it is not. All three builds passed their checks and the full suite.

### review: floor guard (floor.py), 2026-11-25

Idea from addyosmani/agent-skills `constraint-driven-development` (floor guard); script and text written for mstack.

Tested by `tests/scripts/floor_cases.sh` (29 runs, 74 checks, all ok; run in `.testrun/floor-a2`):
- clean change (new code plus a new test) passes; single REF means REF..HEAD; empty range passes;
  a renamed test file and a renamed test function are not counted as removals.
- test-deleted (git rm of a test file), test-removed (Python def and JS it() case), assert-removed,
  assert-loosened (assertEqual -> assertTrue, `assert a == b` -> `assert a`, toStrictEqual -> toEqual).
- threshold-weakened (fail_under lowered, timeout raised); a stronger bar passes; threshold-removed
  (fail_under deleted); retry-added (@pytest.mark.flaky).
- test-skipped (@unittest.skip, pytest.mark.xfail, it.only, xit); focus/skip markers do not also count as removed tests.
- check-disabled (`|| true`, continue-on-error, # type: ignore, # noqa, @ts-ignore, eslint-disable, --no-verify).
- ci-step-removed (a step removed from a workflow) and ci-file-deleted; a changed `run:` line is not a removed step.
- --allow with a real reason accepts (exit 0, lines marked accepted); a non-word, filler or missing reason
  is blocked (exit 2); an --allow for another file is reported as unused and the run still fails.
- unknown range and unknown single ref are blocked; outside a git repository is blocked.
- working-folder mode sees uncommitted edits and untracked files; the script writes nothing
  (file checksums, .git/index and git status unchanged; no .mstack folder made).

Not tested:
- Go, Rust, Java/Kotlin, Swift test patterns (func TestX, #[test], @Test, XCTAssert*, t.Skip) are in the
  script but have no case; GitLab, CircleCI, Jenkins and `.github/settings.yml` required-check removal also have no case.
- BASE...HEAD (merge-base form) has no case.
- Paths with spaces or non-ASCII names, binary files, very large diffs.
- Detection is line-based: a test removed by editing a parametrize list, an assertion weakened across
  several lines, or a threshold moved into another file is not seen. Number direction is by keyword
  (timeout/retry/tolerance higher = weaker; coverage/min/threshold lower = weaker) and can be wrong for
  unusual names.
- The "real words" check on --allow reasons is a heuristic (3 distinct words with vowels, 15+ characters,
  one common word such as "the" or "because"); a determined user can pass it with nonsense.
- Run on mstack itself (working folder) it flags floor_cases.sh, whose test text contains the markers it
  tests for; that is the expected use of --allow. Over the full mstack history it reported 9 added `# noqa`
  lines, all real.
- The SKILL.md step was not exercised by a trigger or benefit eval.

### code-map (new, 2026-11-25)

Script test: `sh packs/dev/tests/scripts/code_map_cases.sh packs/dev "$PWD/.testrun/dev-code-map/run-1"`.
Last run: 76 cases, 76 ok (2026-11-25, `.testrun/dev-code-map-6`). Machine: macOS, Python 3.14.

What the cases cover:
- `callers` on Python: definition, import, call, method call and reference, each `exact` with file:line and
  the enclosing function; a comment, a string and a different name that starts the same
  (`compute_tax_total`) do not match; `node_modules/` and a folder with `pyvenv.cfg` are skipped; a
  same-name method call in a file that imports neither the name nor its module is set apart.
- `callers` on JavaScript (import, call inside a function, comment and string skipped, `formatPriceShort`
  not matched) and Go (comment skipped), all marked `text match`; a qualified method (`Invoice.total`); a
  module path (who imports `src/billing/tax.py`).
- Name not found exits 1 and offers close names (`compute_taxes` -> `compute_tax`); a name with a space
  exits 2.
- `map`: outline with methods per class and import edges; the 120-line cap and `--max-lines 15` on 60
  extra files; a missing folder exits 2.
- `impact` on `A..B` and `A...B`: the changed definition, callers one and two levels out, the test file,
  and the ranked files to read; a bad range and a word that is neither commit nor file exit 2; file paths
  as targets; a rename in the working folder that leaves a caller behind exits 1 with a `BROKEN` line, and
  passes once the caller is updated; a clean working folder is "nothing changed"; outside a git
  repository impact exits 2 while `callers` still works.

Tried by hand, not kept as cases: Rust (`fn`, `struct`, `use crate::...`, `impl X` labelled `impl`) and
Swift (`func`, `struct`, method call) on a small project in `.testrun/dev-code-map-langs`; `callers` and
`impact` on the mstack repository itself (about 1 s for `callers`). Both task fixtures were run by hand:
`finds-callers` gives 6 uses in 4 files with the string and comment left out; `impact-of-rename` ends
`RESULT fail` with `app/report.py:5` ranked third.

Not tested: trigger, silence and benefit evals (`claude plugin eval` not run, as asked). Swift, Rust and
other C-like languages have no kept script cases. Known limits, stated in the SKILL: dynamic calls
(`getattr`, string dispatch, reflection) are invisible; Python `obj.name()` matches any receiver; for a
committed range, callers are searched in the working folder as it is now; text matches in non-Python
languages can include a same-named thing from another module. `packs/dev/.claude-plugin/plugin.json`
description does not yet mention code-map (not touched, per the brief).

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

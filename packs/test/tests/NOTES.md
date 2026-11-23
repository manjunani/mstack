# mstack-test: what was tested

Date: 2026-11-22. All script tests ran on macOS with Python 3.14, each in a fresh folder under `.testrun/`.
Run one as: `sh packs/test/tests/scripts/<file>.sh packs/test .testrun/<new folder>`. Each case states its expected exit code; the last line prints the totals.

| Skill | Script test | Result |
|---|---|---|
| qa-run | `qa_cases.sh` | 66 passed, 0 failed |
| flaky-triage | `flaky_cases.sh` | 48 passed, 0 failed |
| test-cases | `cases_cases.sh` | 46 passed, 0 failed |
| test-gaps | `gaps_cases.sh` | 37 passed, 0 failed |
| test-data | `data_cases.sh` | 63 passed, 0 failed |
| api-check | `api_cases.sh` (with `api_server.py`) | 47 passed, 0 failed |
| bug-report | `bug_cases.sh` | 24 passed, 0 failed |

`python3 tools/validate.py --strict`: all seven `test/` skills show `ok`.

Trigger, silence and benefit tests (`claude plugin eval`) were **not run**: the job forbade it. `tests/results.json` does not exist yet.

## Faults the script tests caught (fixed)

- flaky-triage: `guard` scanned no lines from files git did not track, so a retry setting in a new `pytest.ini` passed. It now reads untracked files too.
- flaky-triage: the test kept a backup copy inside the project, which made the diff look non-empty. The test now keeps it under `.mstack/`, which the scan leaves out.
- flaky-triage: a missing program was found only after a record file had been created. It is now checked before anything is written.
- test-gaps: line counts were one too high, because the last newline was counted as a line.
- test-gaps: `scan` told the user to run `check` on `gaps.md` when it had written `gaps-2.md`. It now names the right file.
- test-data: the loose phone pattern matched the digits inside a UUID. Word characters next to the match now stop it.
- test-data: `repeat_check` reported twice the number of changed lines (each counted as removed and added).
- api-check: the test passed the server a relative log path, so every request crashed the test server. The test now passes an absolute path.
- bug-report: evidence paths in backticks kept the backticks, so existing evidence files showed as missing.

## Per skill: tested and not tested

**qa-run.** Tested: `server.py` start, wait, status, stop against a real `http.server`; a missing program, a command that exits, a port that never opens, a port already held (refused, not killed), an HTTP probe, no stray process left behind. `report.py`: diff scope from git, missing final states, issues lacking steps, expected, actual or evidence, missing and empty evidence files, green scenarios over a red suite, suite not run, nothing to test, broken report file. Not tested: driving a browser. The skill uses the host agent's browser tool, and none was used here. The blocked path for a missing browser exists only as SKILL.md text, with nothing to run. Not tested on Linux.

**flaky-triage.** Tested: repeat runs of a test that fails exactly 1 run in 3 (4 of 12 failed, rate 33.3%), seeds passed through `--seed-flag` and repeatable with `--base-seed`, timeouts counted as failures, all-fail reported as broken, early stop, order bisect finding the one polluter among four candidates, `guard` on skip marks, retry settings, fixed waits and a deleted test, `confirm` rejecting too few runs (needed 8 at 33%), a changed command and a before record with no failure. Not tested: real pytest, jest or go runners (unittest only), parallel-worker mode, a failure that needs two polluters together.

**test-cases.** Tested: `pairwise.py` on 3x3x2 (9 rows, 21 of 21 pairs) and on 6 parameters of 4 values with two exclusions (22 rows instead of 4096). Both were checked by an independent pair counter in the test, along with impossible pairs, output that is the same on every run, and the refusal to overwrite. `cases.py`: four forms of requirement line, two results at once, vague and bare expected results, placeholders, repeated ids, unknown requirement ids, conflicting cases, a requirement with no case, quoted text containing "or". Not tested: specs in formats other than Markdown, or a real spec from the product pack (not built yet).

**test-gaps.** Tested: a project mixing Python and JavaScript with pytest, jest and a GitHub Actions file; untouched files ranked by change count; bare folders; filled gap tables (missing risk, unknown action, short reason, update naming a test that does not exist, add pending, a dropped row); a fully covered project; a folder outside git. Not tested: Go, Rust, Java and Swift projects (the patterns exist and never ran), very large repositories, and CI systems other than GitHub Actions.

**test-data.** Tested: the scanner on fixtures and seeds holding a public-provider email, a company domain (warning), international, North American and keyword phone numbers, a card that passes the Luhn check (also with an expiry after it), an SSN, an Aadhaar number that passes Verhoeff, PAN and NINO shapes. It also had safe counterparts for each. Further cases: the allow list, binary files skipped, an empty scan treated as not verified. Verhoeff and Luhn were checked against known values. `repeat_check.py`: a fixed-seed factory, a random factory, ignored timestamp lines, an appending seed against an upserting seed in SQLite, a seed that crashes on its second run, written files. Not tested: real databases other than SQLite, and non-English names or addresses (the scanner does not look at names). The values in `references/safe-values.json` were written from memory and are marked `verified: false`; the scanner prints that.

**api-check.** Tested against a local `http.server` API started by the test: public, private and non-http hosts refused before any request, YAML and Swagger 2 refused (JSON only), server not running, GET routes matching, write routes skipped without `--write` (the server log shows none arrived), POST and DELETE sent with `--write`, `$ref` and `allOf`, guessed parameters reported, header value never printed, and seven kinds of mismatch, each with request, expected and actual. Further cases: a redirect that is reported and not followed, and `--allow-host`. Not tested: HTTPS, auth flows, nested shape checks (not implemented: top level only), OpenAPI 3.1 type arrays beyond the simple case.

**bug-report.** Tested: reproduction from a clean step on two runs, not reproduced, a different failure that is not counted as the bug, intermittent results, a clean step that fails, a command that cannot start, an exit code used as the marker, evidence folders never overwritten. Lint checks: missing section, steps that are not numbered, expected equal to actual, missing and empty evidence, a GitHub token and a personal email found and not echoed. Not tested: posting to a tracker (the skill never posts by itself), or duplicate search with `gh`, which is not built. The secret patterns are a small set and will miss many token formats.

## Names

No names changed. `qa-run` and `bug-report` overlap a little ("write it up"); the descriptions point each to the other.

- 2026-11-23, api-check task `mismatch-detail`: the prompt now asks Claude to start the fixture server (`python3 api.py`) in the background, because an eval workspace has no running server.

# mstack-product: test notes

Date: 2026-11-22. Python 3.14 on macOS. Everything below was run on throwaway projects under `.testrun/product-<skill>/`.

## How to repeat

Each script test takes the skill's script and a folder that does not exist yet, builds its fixtures there, runs every case and prints `ok` or `BAD` with the exit code. It exits 1 if any case is wrong. The helper is `scripts/casekit.py`.

```
python3 packs/product/tests/scripts/clarify_cases.py            packs/product/skills/clarify/scripts/intent.py            .testrun/product-clarify/run1
python3 packs/product/tests/scripts/spec_cases.py               packs/product/skills/spec/scripts/speclint.py             .testrun/product-spec/run1
python3 packs/product/tests/scripts/trace_cases.py              packs/product/skills/trace/scripts/trace.py               .testrun/product-trace/run1
python3 packs/product/tests/scripts/nfr_budgets_cases.py        packs/product/skills/nfr-budgets/scripts/budgets.py       .testrun/product-nfr-budgets/run1
python3 packs/product/tests/scripts/ideate_cases.py             packs/product/skills/ideate/scripts/options.py            .testrun/product-ideate/run1
python3 packs/product/tests/scripts/compare_options_cases.py    packs/product/skills/compare-options/scripts/compare.py   .testrun/product-compare-options/run1
python3 packs/product/tests/scripts/premortem_cases.py          packs/product/skills/premortem/scripts/assumptions.py     .testrun/product-premortem/run1
python3 packs/product/tests/scripts/research_synthesis_cases.py packs/product/skills/research-synthesis/scripts/evidence.py .testrun/product-research-synthesis/run1
```

## Last results

| Skill | Cases | Wrong | validate --strict |
|---|---|---|---|
| clarify | 23 | 0 | ok |
| spec | 31 | 0 | ok |
| trace | 23 | 0 | ok |
| nfr-budgets | 46 | 0 | ok |
| ideate | 26 | 0 | ok |
| compare-options | 40 | 0 | ok |
| premortem | 33 | 0 | ok |
| research-synthesis | 26 | 0 | ok |

Trigger, silence and benefit tests (`claude plugin eval`) were **not run** for any skill: they cost usage and the builder was told not to run them. `tests/<skill>.json` holds the prompts and tasks; there is no `results.json` yet, so every skill shows as "not tested".

## Faults the script tests found (fixed)

- **clarify**: a `found in repo` path such as `../../x.py` that leaves the project was accepted. Now refused.
- **trace**: without git, a requirement with no code mention was reported as `no-code` (fail) although commits were never searched. It is now "undecided" and the run ends as not verified.
- **trace (test fault)**: the no-git case started failing once the repository root became a git repository, because git found the parent repository. The test now sets `GIT_CEILING_DIRECTORIES`.
- **nfr-budgets**: a pipe whose first tool is missing or fails (`tool | count`) returned exit 0 from the last command and gave a value. Commands now run under `bash -o pipefail`.
- **compare-options**: a flip on a challenger's score was worded "ties with Redis" for Redis itself; a flip that only works through a veto was missed for a dominant option, and the result file kept only five flips. All fixed; the worked example's flip points match a hand calculation and were confirmed by re-ranking past each one.
- **research-synthesis**: a quote on the wrong line was reported at a two-line window that began on a blank line (line 2 instead of 3). Single-line matches are now preferred.

## Per skill: what was tested, and what was not

**clarify** (`intent.py`). Tested: template, refusal to overwrite, every ledger rule (missing label, invented label, `user chose` without rejected alternative or reason, assumed or open item that changes the build, missing or outside path, placeholders, repeated id), unconfirmed file ends blocked, confirmation voided by a later edit, `show` output. Not tested: the questioning itself (one question per turn, stop rule) — that is model behaviour, covered only by the eval tasks, which were not run.

**spec** (`speclint.py`). Tested: required parts, id form and uniqueness, check method and "how", vague words and phrases (word list in `references/vague-words.json`), words inside backticks or quotes ignored, placeholders, open questions, continuation lines, warnings for "and" and length; second mode: `survey` on Flask routes, argparse commands and pytest tests, `--from-code` source existence, line range and outside paths. Not tested: `survey` patterns for Express, Go, Rust/Tauri and JS test files (written, never run on such code). The vague-word list is a judgement list, not a measured value.

**trace** (`trace.py`). Tested on a real git repository with five commits: all four flags (no-test, orphan-test, no-code, gone), id in a test name (`r_002`), commit evidence counting only when a non-test file changed, `measure` checks needing no test, history note saying whether a stray id was ever in the spec, waivers (refused without a reason, for unknown ids, for orphan-test), stale waiver note, no-git path, `--no-commits`, an id defined in two specs. Not tested: large repositories (speed), specs outside `docs/specs/` found by name other than `--spec`, merge commits.

**nfr-budgets** (`budgets.py`). Tested: refusal for each of the five missing fields, word numbers, placeholder conditions, wrong duration units, unknown measure; baseline before check, baseline voided when the command changes, `--runs` median, `at most` and `at least`, all three ways of reading a value, missing tools, failing commands, commands that print no number, pipes, unknown ids, refusal of a deleting command without running anything (the dangerous sample lives only inside the test file, built from parts). Not tested: real benchmarks, network checks, timeouts (the code path exists; no case waits for one), Windows (no bash; falls back to the default shell without pipefail).

**ideate** (`options.py`). Tested: grounding required, target count, reworded duplicates counted once, axes coverage, freezing refused once judging has begun, check before freeze is not verified, removed or retitled options after the freeze, late additions noted, reasons and bases required, two or three survivors, repeated reasons warned. Not tested: the quality of the ideas, and the near-duplicate rule on real lists (it uses word overlap of titles at 80%, which can miss paraphrases).

**compare-options** (`compare.py`). Tested against a hand-worked example: totals, margin, veto, three weight flips, score flips for winner, challenger and a vetoed option, fragile warning, soft scores, ties as fail, all vetoed as fail, every refusal (missing or zero or word weight, missing score, missing or placeholder source, off-scale score, unknown criterion, one option, duplicate names, veto off scale). Each reported flip was confirmed by re-ranking just past it. Not tested: more than five options, or criteria with equal names in different case.

**premortem** (`assumptions.py`). Tested against a hand-worked table: risk order, confidence without evidence counted as 2, confidence capped by a dependency, top-ranked rule (`--top` plus high-impact low-confidence bets), weakest link, cheapest test by time cost, tests missing what, pass or fail lines, identical lines, cost not a time, irreversible note, blocked paths (no plan file, short story, fewer than three rows, bad scales, unknown or circular dependencies, duplicate ids). Not tested: whether the assumptions a model writes are the right ones; that is judgement.

**research-synthesis** (`evidence.py`). Tested on three short invented notes: verbatim match with line ranges and curly quotes, reworded quote, wrong line with the real line named, line past the end, distinct-participant count (two quotes from one person count once, unverified quotes do not count), theme versus anecdote against the threshold, anecdote that reached it, unlisted and missing sources, missing participant, finding with no evidence, coverage percentages and uncited stretches. Not tested: one transcript holding several speakers (the script assumes one participant per source file), non-UTF-8 files, very long transcripts.

## Notes on names and scope

- `spec` holds both modes (new spec, and spec from existing code), as the brief asked; `spec-from-code` from the study note is not a separate skill.
- Requirement ids are `R-001` (three digits or more). `trace` reads them from bullets in a `## Done when` part, or from any bullet starting with an id when the spec has no such part.

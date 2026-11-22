# mstack-ops: what was tested

Date: 2026-11-22. Machine: macOS, Python 3.14. Nothing was installed and no network address other than
127.0.0.1 was contacted. No hosting platform, CI host or database server was touched.

## How to repeat

```
sh packs/ops/tests/scripts/run_all.sh .testrun/ops-all-<n>     # a NEW folder each time
python3 tools/validate.py --strict
```

Last full run: 11 case files, 193 cases, 0 wrong, exit 0 (about 45 seconds). `validate.py --strict`: all 11
`ops/` skills `ok`, no warnings.

Not run: `claude plugin eval` (trigger, silence and benefit tests). The `fire`, `quiet` and `tasks` in
`tests/<skill>.json` are written but have no measured results; `tests/results.json` does not exist yet, so every
skill shows as "not tested". The task graders assume fixture files (for example `backups/app.sqlite`,
`billing/usage.csv`, `db/migrations/0042_cleanup.sql`) that the eval builder must provide; where a file is
absent, the graders accept an honest "blocked".

## Per skill

| Skill | Script | Cases | What ran | What did not run |
|---|---|---|---|---|
| deploy-check | `probe.py` | 15 | Against a web server on 127.0.0.1: version in a header and in the body, wrong version, 500, empty body, redirect reported and not followed, time limit over and under, nothing listening, non-http and credential URLs refused, record file written or skipped | HTTPS with a real certificate; a real deploy; a service that swaps instances slowly |
| env-check | `envnames.py` | 10 | A project with TS, Python and Rust reads (including destructuring and dynamic reads); example file with a commented name; set-names as `NAME=value`, bare names and JSON; every case asserts that none of five planted values is printed | Go, Ruby, Deno and Bun patterns are in the script but have no case; a real platform export |
| migration-check | `sqlrules.py` | 14 | All 14 rules fire on one file at the right lines; sibling down files and in-file down markers; tables created in the same files exempt; old names found in code; dollar-quoted function bodies and strings with `;` not split; mysql run ends not verified | Applying to any database (the skill never does); MySQL and SQLite lock rules (skipped by design); the PostgreSQL lock claims themselves are unverified, written from memory |
| restore-test | `restore.py` | 30 | SQLite file, SQL dump and gzipped dump restored into new folders; counts with tolerance; truncated file, truncated dump and empty file fail; a dump that tries `ATTACH` is stopped; tar and zip with counts, paths and sha256 manifest; entries that leave the folder skipped; backup and live file hashes unchanged; checklist mode with user-supplied counts; a scratch name like `app_production` refused | Any restore of PostgreSQL, MySQL or MongoDB (the script prints steps only); the tool names in `engines.json` are unverified |
| perf-check | `measure.py` | 19 | A program whose sleep times the test controls: no change (inside the noise), 900 ms slower (fail), 420 ms faster (pass), noisy timings (not verified), failing command, missing command, name that leaves the folder, `--replace` keeps the old baseline | Timing on another machine (detected and refused, not tested); the noise defaults are unverified |
| ci-check | `workflow.py` | 17 | The YAML reader's output for a full workflow compared field by field, with line numbers; a bad workflow where 15 findings must appear on exact lines; tag pins as warning and with `--require-sha`; JSON workflows; anchors, tabs, open `[..]`, several documents and empty files end as not verified | The platform's own validation; expression syntax; action inputs; whether commands exist; the list of top-level keys is from memory |
| ci-fix | `cilog.py` | 18 | A GitHub Actions log with colour codes and timestamps: first failing step, command, exit code, commit, tool version, environment names, later errors excluded; the tab-separated download form; a plain log with `$` commands; an action as the failing step; reproduce with the same error (numbers differ), a different error and a pass; long hostile lines shortened | A real downloaded log from GitHub; GitLab and other hosts' formats beyond the plain `$ cmd` form |
| dep-upgrade | `upgrade.py` | 26 | A full upgrade on `package-lock.json`: start, changelog sections between versions, tests before, upgrade, tests after, check passes; a major upgrade that breaks the tests fails; missing target section; a stale after run; reading versions from poetry.lock, Cargo.lock, go.mod, Gemfile.lock, requirements.txt, yarn.lock and pnpm-lock.yaml | Running any real package manager (nothing installed); uv.lock, pyproject.toml and Cargo.toml parsing have no case |
| rollback | `rollback.py`, `probe.py` (copy of deploy-check's) | 19 | Plan with each part missing, data unknown and incompatible, no-op rollback, chained command refused; apply without `--execute` runs nothing and changes nothing; apply with it runs a local program that switches the served version; confirm before (fail) and after (pass) against 127.0.0.1; failing and missing rollback command | Any real platform rollback; `references/providers.md` is unverified |
| cost-watch | `usage.py` | 13 | A CSV export whose sums were worked out by hand (98.00 spent, 173.00 projected) against three limits; JSON export with other column names; growth flagged and not flagged; two days of data; mixed currencies; columns that cannot be guessed and named ones | A real provider export (column names of Vercel or Railway exports were not checked); the growth floors are unverified |
| log-triage | `triage.py` | 12 | Plain log: four groups with ids and numbers masked, first error, the deploy and new lines before it, groups after `--after`; JSON lines with numeric and named levels; clean log; log without levels; error on line 1; long hostile line shortened | Multi-line stack traces are grouped line by line, not as one event; syslog timestamps are parsed but have no case |

## Faults the tests caught and that were fixed

- restore-test: two runs in the same second asked for the same scratch folder and the second ended blocked.
  The script now adds `-2`, `-3`; it still never reuses an existing folder.
- perf-check: the "spread too wide" rule overrode a clear difference (a 57% faster run was not verified).
  The spread veto now applies only when the difference is inside the noise.
- perf-check and ci-fix: options written after the positional argument (`--cwd`) were swallowed into the
  command, and perf-check dropped every `--` inside the command. Both now split at the first `--` only.
- perf-check: a failing command's output was printed after the blocked line, so the last line was not the result.
- ci-check: line numbers for `run: |` blocks pointed one line early; a second document after `---` gave a
  confusing message. Both fixed.
- dep-upgrade: `check` ignored that an "after" run had been made on the old version; after the lock changed,
  that stale run counted as proof. Runs now record the versions they saw and stale ones are rejected.
  A nested copy of the package in the lock file also hid "the upgrade did not happen".
- Test errors fixed in the tests, not the scripts: two hand-counted line numbers (log-triage) and one
  hand-summed window (cost-watch) were wrong.

## Known limits

- The perf-check cases measure real time. On a busy machine a case is retried up to three times and the retry is
  printed. Earlier runs during this build, with other builders working in parallel, needed those retries.
- All thresholds in `references/*.json` are mstack starting values marked `"verified": false`, and the scripts
  print that. Provider notes in `rollback/references/providers.md` are unverified.
- Skill names follow `docs/SKILLS.md`. No name was found to be wrong.

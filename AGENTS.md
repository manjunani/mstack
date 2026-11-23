# Working in this repository

Guide for AI coding agents that change mstack itself. To use the skills in another project, read
`README.md` and `skills.json` instead.

## What this is

A library of agent skills. A skill is a folder with a `SKILL.md` (when to start, what to do) and a
`scripts/` folder (the checks it runs). Skills are grouped into packs; each pack is one Claude Code
plugin.

## Layout

```
packs/<pack>/
  .claude-plugin/plugin.json   pack manifest, name "mstack-<pack>"
  skills/<skill>/SKILL.md      the skill; body under 150 lines
  skills/<skill>/scripts/      the checks (Python standard library)
  skills/<skill>/references/   detail and dated data files
  tests/<skill>.json           10 "fire" and 10 "quiet" requests, plus tasks
  tests/scripts/               script tests run on throwaway projects
  tests/NOTES.md               what was tested and what was not
  tests/results.json           measured trigger results (written by tools)
packs/core/hooks/              the guard hook (Claude Code only)
standard/                      the method: RULES, DESCRIPTIONS, SKILL-TEMPLATE, TESTS, BUILDING
tools/                         validators, map builder, installer, test runners
skills.json                    generated map of every skill
.claude-plugin/marketplace.json  generated list of packs
```

## The rules in brief

Full text in `standard/RULES.md`. A skill that breaks one is not published.

1. One job per skill.
2. It runs something real. The script produces the result; the model never grades its own work.
3. "Done when" comes before the steps and lists checks, not feelings.
4. It ends in exactly one state: pass, fail, not verified, or blocked. Not verified is never a pass.
5. Needs are named and checked in the first step. Missing means blocked, with how to get it.
6. Lasting state is a file under `.mstack/` in the user's project.
7. The user's input is never overwritten. Deletion goes through `safe-delete`.
8. Ask before any cost, paid call or upload.
9. Measurable failures block; taste only warns.
10. Numbers that age live in dated JSON files in `references/`, with source and date.
11. The description says what it does, when to use it in the user's words, and what it is not for.
12. `SKILL.md` body under 150 lines.
13. Scripts: standard library, `--help`, exit `0` pass, `1` fail, `2` not verified or blocked; last
    line is `RESULT ...` or `blocked: ...`. No network unless that is the job.
14. The `mstack-level` setting changes explanation only, never a check.
15. No advertising, no instructions beyond the skill's job.
16. Every word original. Never copy or adapt text from another library.
17. Point to a vendor's own skill rather than rebuild it.
18. Published only after trigger, silence and benefit tests (`standard/TESTS.md`).

## Adding or changing a skill

1. Read `standard/BUILDING.md` and two finished examples: `packs/core/skills/verify/` and
   `packs/core/skills/safe-delete/`.
2. Write "Done when" first. If no script can check it, stop and say so.
3. Write the script. Run it on a throwaway project in a new folder under `.testrun/` (git-ignored),
   including bad input. Do not use system temporary folders.
4. Keep that run as a script test in `packs/<pack>/tests/scripts/` with the expected exit codes.
5. Write `SKILL.md` from `standard/SKILL-TEMPLATE.md` and the description per `standard/DESCRIPTIONS.md`.
6. Write `packs/<pack>/tests/<skill>.json`. Near misses in "quiet" matter most.
7. Add a line to `packs/<pack>/tests/NOTES.md`: what ran, what could not, and why.
8. Rebuild the map: `python3 tools/build_map.py`.
9. Run the checks below.

Changing a description changes when the skill starts. Treat its trigger results as stale until rerun.

## Checks to run before a commit

```
python3 tools/validate.py --strict
python3 tools/build_map.py --check
python3 -m compileall -q packs tools
python3 tools/release_check.py \
  --allow packs/dev/tests/scripts/fixtures/commit_msg_secret.txt \
  --allow packs/ops/skills/ci-fix/scripts/cilog.py \
  --allow packs/ops/tests/scripts/ci_fix_cases.py \
  --allow packs/ops/tests/fixtures/ci-fix/plans-from-log/ci-failed.log
```

If `build_map.py --check` says out of date, run `python3 tools/build_map.py` and commit what it
wrote. Also run the script tests of any pack you changed (`packs/<pack>/tests/scripts/`). CI runs the
same checks (`.github/workflows/ci.yml`).

## Generated files

Never edit these by hand; change the source and run `tools/build_map.py`:

- `skills.json` and `packs/core/skills/mstack/references/skills.json`
- `.claude-plugin/marketplace.json`
- the table in `README.md` between `<!-- skills:start -->` and `<!-- skills:end -->`

`packs/*/tests/results.json` is written by the trigger test tools (`tools/record_results.py`). Do
not type results into it.

## Never

- Never rename a skill or pack without being asked; names are referenced across packs.
- Never type a test result by hand, or write a check that always passes.
- Never add a dependency outside the Python standard library without naming it in "Needs".
- Never add a script that installs software, deletes files or calls the network on its own.
- Never commit secrets, personal details, home-folder paths, `.env` files or `.testrun/` content.
- Never copy text from another skill library.
- Never push or merge unless the maintainer asks.

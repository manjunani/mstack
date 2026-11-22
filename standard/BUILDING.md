# Building a pack

How to add a pack of skills to mstack. Read this once, then read the four other files in this folder: `RULES.md`, `DESCRIPTIONS.md`, `SKILL-TEMPLATE.md`, `TESTS.md`.

## Before writing

1. Read the pack's study note in `research/<pack>.md`, all of it. It says what existing skills do well, how they fail, and which techniques are worth taking. Take ideas. Never take text.
2. Read the pack's section in `docs/SKILLS.md` for the agreed list of skills.
3. Read two finished skills as examples of the standard: `packs/core/skills/verify/` and `packs/core/skills/safe-delete/`, with their scripts, their test files in `packs/core/tests/`, and the script tests in `packs/core/tests/scripts/`.

## Layout of a pack

```
packs/<pack>/
  .claude-plugin/plugin.json     name "mstack-<pack>", description, version, author, license, repository, keywords
  skills/<skill>/SKILL.md        from the template; body under 150 lines
  skills/<skill>/scripts/        the checks
  skills/<skill>/references/     detail and dated data files, loaded only when a step says so
  tests/<skill>.json             10 fire prompts, 10 quiet prompts, at least 2 tasks
  tests/scripts/                 script tests: run the skill's scripts on a throwaway project
  tests/NOTES.md                 what was tested, what was not, and why
```

Copy `packs/core/.claude-plugin/plugin.json` and change the name, description and keywords.

## Order of work for one skill

1. **Write "Done when" first.** If you cannot state a check a script can run, the skill is not ready to be written. Say so in `tests/NOTES.md` and move on.
2. **Write the script.** It is the skill. The `SKILL.md` only tells the model when and how to run it and how to judge what it prints.
3. **Run the script** on a small throwaway project and on bad input. Make the throwaway project in a new folder under `.testrun/` in the repository root (it is git-ignored). Do not use system temporary folders: some checks treat those specially.
4. **Keep the run as a script test** in `tests/scripts/`, with the expected exit code beside each case, so anyone can repeat it.
5. **Write `SKILL.md`** from the template.
6. **Write `tests/<skill>.json`.** Near misses in `quiet` matter most: requests that belong to the neighbouring skill.
7. **Validate.** `python3 tools/validate.py --strict` must show `ok` for the skill.

## Scripts

- Python, standard library only. Use Node only where the job needs it (a browser, a 3D or media toolkit), and then name every dependency in "Needs".
- `argparse`, a docstring that explains every command, and `--help`.
- Exit codes: `0` pass, `1` fail, `2` not verified or blocked.
- The last line printed is `RESULT pass`, `RESULT fail: <why>`, `RESULT not verified: <what>` or `blocked: <what is needed>`.
- Validate the output, not the exit code of the tool you called. An empty result is an error. A black image is not a render.
- Never overwrite the user's input. Write to a new file or folder and say where.
- State that must last goes under `.mstack/` in the user's project. Add what should not be committed to `.mstack/.gitignore`.
- No network access unless the network is the skill's job, and then only to the address the user gave.
- Never run a destructive command. Never install anything. If a tool is missing, print what is missing and how the user can get it, and exit `2`.
- Before any paid call or upload, the skill asks. The script takes an explicit flag for it and refuses without the flag.

## Numbers that age

Thresholds, platform limits, budgets and presets go in a JSON file in `references/`, never in prose. Every entry has:

```json
{ "value": 16, "unit": "LUFS", "source": "<where it comes from>", "checked": "2026-11-22", "verified": false }
```

Set `"verified": true` only when you read the number in the primary source during this work. If you are writing it from memory, it is `false`, and the script prints a line saying the value is unverified. Do not present a remembered number as a fact.

## When a tool is not available to you

Many skills need a tool that may not be on the machine where you build (a 3D program, a headset, a media library, a browser driver).

- Write the script so it detects the tool and ends as blocked when it is absent. Test that path.
- Test everything that does not need the tool.
- Record in `tests/NOTES.md`, per skill: what ran, what could not run and why. "Not run" is an acceptable entry. An untested claim that something works is not.

## Names and neighbours

- Skill names are fixed by `docs/SKILLS.md`. If a name is wrong, say so in `tests/NOTES.md`; do not rename.
- A description's "Not for" names a real skill from `docs/SKILLS.md`, in this pack or another.
- A skill does not depend on another pack's files. It may tell the model to use another skill "if installed" and must say what to do when it is not.

## What a pack must not contain

- Text copied or adapted from another skill library.
- Advice with nothing to run.
- A role or a persona ("you are a senior engineer").
- Advertising, install commands for itself, or instructions to the model beyond the skill's job.
- A check that always passes, a script that prints sample results when given no input, or a result typed by hand.
- Anything that helps a user deceive: fake reviews, invented numbers, evading bot detection, defeating AI detectors.

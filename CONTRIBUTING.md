# Contributing to mstack

Thank you for helping. mstack stays useful only if every skill does one job, runs something, and is tested for when it starts. These rules keep it that way.

## Ways to help

| You want to | Do this |
|---|---|
| Report that a skill started when it should not, or stayed quiet when it should have started | Open an issue with the **Skill started at the wrong time** form. These are the most useful reports. |
| Report a script that crashed or gave a wrong result | Open an issue with the **Bug** form |
| Propose a new skill | Open an issue with the **New skill** form first. Do not start with a pull request |
| Report a security problem | Do not open an issue. Follow `SECURITY.md` |
| Fix a typo or a small bug | Open a pull request directly |

## Issues

- One problem per issue.
- Search first; add to an existing issue rather than opening a second one.
- Include the exact words you typed to the agent, the agent and its version, the pack and its version, and what happened. Without the exact words a trigger report cannot be tested.
- Remove secrets, personal data and private file paths from anything you paste.

## Pull requests

### Before you open one

1. Read `standard/RULES.md` and `standard/BUILDING.md`.
2. For a new skill, have an issue where the maintainer agreed the skill fits.
3. Run the checks locally. All must pass:
   ```
   python3 tools/validate.py --strict
   python3 tools/build_map.py
   python3 tools/release_check.py
   claude plugin validate . --strict
   ```
   and the script tests of the pack you changed, in `packs/<pack>/tests/scripts/`.

### What a pull request must contain

- **One change.** A new skill, a fix, or a description change. Not several.
- **A new skill:** `SKILL.md` from the template, its script, `tests/<skill>.json` with 10 requests where it should start and 10 near misses where it should not, script tests you ran, and a line in the pack's `tests/NOTES.md` saying what was tested and what was not.
- **A description change:** the request that went wrong, and the trigger test run before and after, if you can run it (`tools/run_triggers.sh`). Do not weaken a test to make it pass; change the skill or its description instead.
- **A changed number** (a limit, a threshold, a price): the primary source it comes from, in the data file, with the date you checked it.
- The generated files (`skills.json`, `.claude-plugin/marketplace.json`, the README table) updated by `tools/build_map.py`, not by hand. The pre-commit hook in `tools/hooks/` does this for you.

### What will not be merged

- Text copied or adapted from another skill library, or from anything you do not have the right to share. Write it yourself.
- A skill that only gives advice, or is a role ("you are a senior designer").
- Advertising, links to paid services as the default, install commands for something else, or instructions to the agent beyond the skill's job.
- Scripts that use the network without it being the skill's job, install packages, run destructive commands, or read credentials.
- Anything that helps deceive people: fake reviews or testimonials, invented numbers, getting around bot detection or rate limits, defeating AI detectors.
- Test results typed by hand. Results come from `tools/record_results.py`.

### Review

- Only the maintainer merges. `main` accepts changes only through a pull request that the maintainer has approved and that passes the checks; nobody else can merge, even with write access, until the maintainer approves.
- Every pull request is reviewed by the maintainer (see `.github/CODEOWNERS`). Changes to hooks, `tools/` or `.github/` get a closer look because they run without being asked.
- Workflows for first-time contributors run after the maintainer approves them.
- Pull requests are squash-merged, so the title becomes the commit message. Write it as a plain sentence: what changed.

## Commits

- Plain sentences, saying what changed and why.
- Use an email address you are happy to publish. GitHub's no-reply address works.

## Licence

By contributing you agree that your contribution is published under the MIT licence of this repository, and that you wrote it or have the right to submit it.

## Conduct

Everyone taking part follows `CODE_OF_CONDUCT.md`.

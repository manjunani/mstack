## What changed

<!-- One change per pull request. Say what and why in plain sentences. -->

Closes #

## Type

- [ ] Fix to a script
- [ ] Description change (a skill started at the wrong time)
- [ ] New skill (the issue where it was agreed is linked above)
- [ ] Changed number (limit, threshold, price), with its primary source in the data file
- [ ] Docs or tools

## Checks I ran

- [ ] `python3 tools/validate.py --strict` passes
- [ ] `python3 tools/build_map.py` run, generated files committed
- [ ] `python3 tools/release_check.py` passes
- [ ] Script tests of the changed pack pass (`packs/<pack>/tests/scripts/`)
- [ ] For a description change or new skill: trigger tests run (`tools/run_triggers.sh`), results recorded by `tools/record_results.py`, not typed by hand

## What I could not test

<!-- Tools you did not have, paths that did not run. "Nothing" is a fine answer if true. -->

## Confirmations

- [ ] I wrote this myself; nothing is copied from another skill library
- [ ] No secrets, personal data or private paths are included
- [ ] The script does not use the network, install anything or delete anything unless that is the skill's stated job

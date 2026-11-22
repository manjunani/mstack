# mstack-writing: what was tested

Date: 2026-11-22. Python standard library only; no other tool is needed.

Script test: `tests/scripts/writing_cases.py`, run from the repository root with a new folder:

```
python3 packs/writing/tests/scripts/writing_cases.py .testrun/writing
```

Last run 2026-11-22: 31 run, 0 wrong (16 copyedit cases, 15 translate-check cases). Each case states its expected exit code.

Trigger, silence and benefit tests (`tests/<skill>.json`) are written but were NOT run (`claude plugin eval` was out of scope). No `results.json` exists.

## copyedit

Tested: a clean edit passes with counts by category; failures for an unlisted change, changed code, a reworded quotation, a changed link, a changed number, a dropped name, a query applied as a change, a correction with no rule, a rule missing from the guide, a listed change not in the original; an accepted suggestion; the second-pass check with and without new corrections; a bad list file.

Not tested or not checked:
- The edit itself is made by the model; the script proves only that the edit matches its list and kept protected items. It cannot judge whether a correction is right.
- Name detection is a heuristic (capitalised words not starting a sentence, all-capitals words). A name at the start of a sentence is not tracked.
- Quotations are found for straight double quotes and curly double quotes only; single-quoted passages are not protected.
- The "second run finds nothing new" check needs a second list made by the model; the script cannot make it.
- The house style (`references/house-style.md`) is original text written for mstack, short on purpose.

## translate-check

Tested: a faithful text translation passes; failures for a translated placeholder, a reformatted number (and the `--loose-numbers` opt-in), a changed web address, a dropped tag, a glossary term translated another way, a name translated, an empty translation, a length ratio; strings files: complete, missing and empty keys, a placeholder lost in one key, a per-key length limit, a source that is not JSON.

Not tested or not checked:
- Translation quality, accuracy and tone. The script says so on every run.
- Plural forms (ICU `{count, plural, ...}`) are matched as one placeholder by their first part only; nested plural text is not compared.
- Scripts without spaces between words (Chinese, Japanese, Thai) were not tested with the glossary check, which uses word boundaries.
- Numbers written in non-Latin digits are not recognised as numbers.

Neither skill rewrites text to defeat AI detectors; copyedit's SKILL.md says so and a task in `copyedit.json` checks the refusal.

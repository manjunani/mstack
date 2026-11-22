# The mstack standard

Every skill in mstack follows these rules. A skill that breaks one is not published.

They come from two sources: a study of existing skills across 12 public libraries (23,064 skill files, about 300 of them read closely), and a record of which skills one developer really used over several hundred coding sessions. The short version of what that showed: skills that give advice get ignored or cannot be checked; skills that run something and end with a result get used.

## 1. One job

A skill does one thing. If describing the job needs the word "and", it is two skills, or one skill with a reference file.

## 2. It runs something

A skill must run or check something real: a script, a command, a tool, a render, a test. A skill that only tells the model what to think about is rejected, however good the advice.

The check is produced by a script, not typed by the model. The model does not report its own result.

## 3. Done is stated first

The section "Done when" comes before the steps. It lists checks a person or a script can run. No feelings ("clean", "fast", "good").

## 4. Four end states

Every skill ends in exactly one:

| State | Meaning |
|---|---|
| **pass** | The checks ran and passed |
| **fail** | A check ran and failed; the failing output is shown |
| **not verified** | A check could not run; says which and why. Never counts as a pass |
| **blocked** | Cannot go on without the user: a decision, a missing tool, a permission |

"Nothing to do" is a pass with that reason given. A skill is never forced to find something.

## 5. Needs are named and checked

A skill lists what it needs (ffmpeg, a browser, git, an API key) and checks for it in its first step. If something is missing, it says what and how to get it, and ends as blocked. It does not pretend, and it does not download or install anything without asking.

## 6. State lives on disk

Anything that must survive a long session or be read by another skill is a file: evidence records, ledgers, manifests, cut lists. mstack files in a user's project go under `.mstack/`.

## 7. Originals are safe

A skill never overwrites the user's input. Output goes to a new file or folder. Anything destructive goes through `safe-delete`.

## 8. Ask before cost or upload

Before spending money, calling a paid API, or sending the user's content to an outside service, the skill states the cost or the destination and waits for a yes.

## 9. Taste warns, facts block

A measurable failure (contrast below the limit, a test that fails, a file over budget) blocks. A judgement of taste (looks generic, could be shorter) is a warning the user may ignore.

## 10. Numbers that age are dated

Platform presets, thresholds and budgets live in a data file in `references/`, each with its source and the date it was checked. They are never written into the skill's prose as timeless facts.

## 11. The description is written to trigger

See `DESCRIPTIONS.md`. The description says what the skill does, when to use it in the user's own words, and what it is not for, naming the neighbouring skill.

## 12. Short

The body of `SKILL.md` stays under 150 lines. Detail goes into `references/`, loaded only when needed. Checks go into `scripts/`.

## 13. Scripts

- Python standard library only, unless the domain truly needs more (a browser, a 3D toolkit). Then Node, with dependencies stated in "Needs".
- Every script has `--help` and prints what it checked.
- Exit codes: `0` pass, `1` fail, `2` not verified or blocked (a missing tool, bad input).
- A script reads and reports. It changes the user's files only when that is the skill's stated job, and never silently.
- No network calls except where the skill's job is the network, and then only to the address the user gave.

## 14. Level

The user sets one line in `CLAUDE.md` or `AGENTS.md`: `mstack-level: beginner`, `standard` or `expert`. Default is `standard`. It is never guessed.

The level changes how much a skill explains and how many questions it asks. It never removes a check, a safety step or a confirmation.

## 15. Clean text

A skill contains no advertising, no instruction to install or promote anything, and no instruction to the model beyond the skill's job. It never tells the model to ignore the user or other rules.

## 16. Original

Every word is written for mstack. Other libraries are studied for ideas; their text is not copied or adapted.

## 17. Vendors

Where a vendor ships a good skill for its own product, mstack points to it and does not rebuild it. mstack skills still work when the vendor's skill is not installed.

## 18. Tested before published

A skill is published only when it passes its trigger, silence and benefit tests (see `TESTS.md`). A pack is published only when all its skills pass.

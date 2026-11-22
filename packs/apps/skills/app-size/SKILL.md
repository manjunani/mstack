---
name: app-size
description: Measures a built .app or .ipa by part (executable, frameworks, Assets.car, resources) and lists the largest files, keeps a baseline under .mstack, and shows what grew, what is new and what was removed since that baseline. Use when the user asks "how big is the app", "why did the download get bigger", "what grew in this build" or wants a size limit on an iPhone or Mac build. Not for web bundle size (use verify with the project's own budget check).
license: MIT
metadata:
  pack: apps
  version: 0.1.0
  needs: python3
---

# App size

Produces a size table by part, a list of the largest files and, against a saved baseline, a list of what changed.

## Done when

- `scripts/appsize.py measure` printed the table for the build the user named.
- With a baseline: `scripts/appsize.py compare` exits 0, or exits 1 naming the limit passed.
- The reply says these are bytes in the bundle, not the size the App Store shows a user.

End in exactly one state: **pass**, **fail** (a limit the user set was passed), **not verified** (no baseline yet, or the archive could not be read), or **blocked** (no build found).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| A built .app or .ipa | the path exists | build with the project's own command, or ask; blocked |

## Steps

The script is `scripts/appsize.py` (`"${CLAUDE_SKILL_DIR}/scripts/appsize.py"` in Claude Code).

1. **Measure.** `python3 scripts/appsize.py measure <App.app or App.ipa>`.
2. **Baseline.** If there is none and the user wants comparisons later: `measure <path> --save`. Replacing an existing baseline needs `--replace` and the user's yes; the old one is kept under a dated name.
3. **Compare** a later build:
   ```
   python3 scripts/appsize.py compare <path> [--max-growth-percent 5] [--max-bytes N]
   ```
   Limits come from the user. With none, the result is a report and passes.
4. **Explain the top change** by opening it: a new asset, a framework, debug symbols left in.
5. **Report.** End state, total and change, the three biggest changes, the baseline used.

## Rules

- Never invent a size limit; use the user's, or report only.
- Measure release builds against release builds; a debug build is larger and says nothing about the shipped app.
- The App Store's thinned download size comes from Apple's own report; that is the source for what users download.

## Not for

- Web bundle budgets → use `verify` with the project's own check.
- Launch time → not covered by this pack.
- Checking signatures of the build → use `mac-release-verify`.

## Level

- beginner: explain what each part of a bundle holds.
- standard: as written.
- expert: total, change and RESULT line. The measurement always runs.

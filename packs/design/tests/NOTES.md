# mstack-design: what was tested

Date: 2026-11-22. Built offline: no network, nothing installed. The machine had Python 3.14, Node, and the macOS `sips` image tool. It had no Playwright, no axe-core, no ImageMagick and no Pillow.

## Script tests

One runner covers every skill: `tests/scripts/design_cases.py`. It copies the hand-written fixtures in `tests/scripts/fixtures/<skill>/` into a fresh `.testrun/design-<skill>/run-<n>/` folder, runs each case, and checks both the exit code and a piece of text the output has to contain. The ui-match cases make their PNG files with their own small encoder, which is separate from the skill's reader.

```
python3 packs/design/tests/scripts/design_cases.py            # all skills
python3 packs/design/tests/scripts/design_cases.py --only ui-match
```

Last run: **115 cases, 0 wrong, 0 not run.**

| Skill | Cases | What they cover |
|---|---|---|
| design-review | 17 | merge; a good page passes at 320/768/1440; a bad page blocks on overflow, clipping, contrast, missing names, crowded small targets and placeholder text; taste traits only warn; missing widths or themes are not verified; text on an image is not verified until a waiver with a reason clears it; waivers without reasons, empty views and non-snapshot files are refused; a snapshot captured by `collect.js` in a real browser |
| a11y-audit | 15 | `needs` blocks in a project with no Playwright or axe-core; AA violations fail and best-practice rules only warn; level A; baseline save, refusal to save twice, fixed/remaining/new after a fix; keyboard log with invisible focus, a trap, an unreached control and a failed Escape check; no keyboard log is not verified; an empty axe result means the scan did not run; a narrower run than the baseline is not verified; `run_axe.mjs` ends as blocked without its dependencies |
| token-check | 18 | contrast failures in light and dark, each with a same-hue proposal; a passing file; waivers with and without reasons; an `oklch()` value is not verified rather than passed; an explicit pairs file; Tailwind literal colours, with a computed entry reported as skipped; drift finds hard-coded colours and off-scale sizes; accepted values drop out and unused accept entries are reported; a link target such as `#add` is not read as a colour; reports are never overwritten |
| ui-build | 10 | blocking lint on filler text, a TODO marker, a dead handler, a dead link, invented proof and a removed focus outline; default-look traits only warn; an outline removed with a `focus-visible` ring is accepted; round 1 to 3 are recorded and round 4 is refused; a round with no real note is refused |
| ui-match | 33 | RGB against RGBA with all five PNG filter types; each filter type decodes to the same pixels as unfiltered; noise inside and outside the tolerance; a moved button fails only in its regions; a difference kept on purpose with a reason; a 2x screenshot averaged down; a flat image is not a render; palette, greyscale, 16-bit and interlaced PNG, a checksum error, a truncated file, a JPEG and a missing file all exit 2 with the reason; diff image written and readable; never overwritten; three recorded rounds end as blocked. Two extra cases decode a test image and a PNG re-saved by the system encoder (`sips`) and compare every pixel with the system's own BMP output: equal |
| ui-copy | 11 | a bad flow: one action with two names, vague buttons and links, a dead-end error, raw error text, placeholder text; an error with a fix button beside it is not a dead end; a good flow passes; a JSX source scan where commented-out markup is ignored; a strings file; answers with and without reasons; no markup is not verified; inventory written once |
| brand-kit | 11 | off-kit colours, a font and a banned phrase listed with file and line; a colour within tolerance of a brand colour counts as in the kit; a clean stylesheet passes; a page snapshot checked against the kit; an unconfirmed brand file is refused unless `--draft`; missing brand file; nothing to check; `init` writes once and never overwrites |

## Faults the tests caught (fixed)

- design-review: the small-target rule first counted a neighbour as "crowding" only when it overlapped the target's centre box, so two 20 px icons 2 px apart passed. Now each target claims a 24 px area around its centre and any overlap blocks.
- ui-copy: the raw-error pattern ran case-insensitive, so its test for error codes such as `ENOENT` matched the word "ended" and a plain sentence ("Your session ended...") was called internal error text; the good flow failed. The pattern is now case-sensitive where it should be.
- ui-copy: an error message with an "Update card details" button under it was treated as having no way forward because the nearby-action test used a fixed vertical window. It now pairs an error with actions in the same container or directly below it.
- ui-copy: the case-style warning called "Delete project" Title Case. The test of a label's style was rewritten.
- token-check: Tailwind colours that do not change with the theme were measured twice (light and dark) and reported twice.
- token-check: drift scanning missed values in one-line CSS rules (`.card { padding: 13px; }`) and counted token definitions as uses.
- Three expectations in the test runner were wrong (my own counting, not the scripts): a moved button spans two grid rows, so four regions differ, not two; and `#1e4fd9` is within tolerance of the brand navy, so two colours are off-kit, not three. The expectations were corrected after reading the outputs.

## Live browser steps

- **design-review `collect.js`: run once in a real browser** (the desktop app's browser pane, Chromium-based) on `fixtures/design-review/page.html`, at its one available width of 626 px. The result is saved as `fixtures/design-review/live-626.json` and is checked by the runner. It correctly reported: sideways overflow (900 px page), an unnamed button, two crowded 20 px buttons, pale text, text faded by `opacity` (folded into the colour's alpha), text on a gradient as unknown background, a clipped heading, filler Latin, an image with no alt text, a decorative image as decorative, a label-named input, an inline link and a screen-reader-only skip link. Not run: other widths, a dark theme, Playwright `page.evaluate`, and the console-paste path.
- **a11y-audit `run_axe.mjs`: not run against a page.** Playwright and axe-core are not installed here and installing was not allowed. Only its blocked path was run. The axe JSON and keyboard logs in the fixtures are written by hand to the shape axe-core documents; the keyboard focus-visibility test inside `run_axe.mjs` has never run.
- **ui-build render step, ui-match screenshot step, ui-copy and brand-kit snapshot capture: not run live.** They reuse a browser the host provides; their scripts were tested on files.

## Not tested

- Trigger, silence and benefit tests (`claude plugin eval`) were not run, by instruction. `tests/<skill>.json` files are written; `results.json` does not exist yet.
- `tools/build_map.py` was not run, by instruction.
- token-check: Tailwind configs that use `require`, spreads or functions are read only for their literal colours; no real project's config was tried. CSS in `@layer` or nested inside `@supports` was not tried.
- brand-kit capture mode is judgement and the user's confirmation; only `init` and `check` are scripted.
- All limits and word lists in `references/*.json` were written from memory and are marked `"verified": false`. The WCAG numbers (4.5, 3.0, 24 px targets, 320 px reflow, large text sizes) should be read in the WCAG 2.2 text and the entries set to verified.

## Names

No name from `docs/SKILLS.md` was changed. The study note asked whether `design-review` sits too close to core `review` and `verify`; the description names `review` as its neighbour, and only the trigger tests can show whether that is enough.

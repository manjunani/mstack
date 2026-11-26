---
name: brand-kit
description: Captures the user's own brand into one brand.json file (colours with use and never rules, fonts, voice with banned phrases) and checks pages, stylesheets or copy against it, listing every off-brand colour, font and phrase with its location. Use when the user says "keep it on brand", "use our brand colours", shares brand guidelines or a style guide, or asks whether a page matches the brand. Not for contrast of design tokens (use token-check) or general interface wording (use ui-copy).
license: MIT
metadata:
  pack: design
  version: 0.3.1
  needs: python3
---

# Brand kit

Produces one brand file the user confirmed, and a check that lists every value in the work that is not in it.

## Done when

- Capture: `brand.json` exists, every value in it came from the user's own material, and the user said it is right (`"confirmed": true`).
- Check: `scripts/brand.py check` exits 0, or every off-kit item is listed with its location and the user decided about each.

End in exactly one state: **pass**, **fail** (off-kit items listed), **not verified** (nothing to check was found, or the brand file is still a draft), or **blocked** (no brand material from the user to capture from).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| The user's brand material | a site, guidelines, logo files, existing stylesheets or a page snapshot | ask for it; never invent a brand; end as blocked |

## Steps

The script is `scripts/brand.py` in this skill's folder.

1. **Start the file** (capture mode, once):
   ```
   python3 scripts/brand.py init --out brand.json
   ```
2. **Fill it from the user's material only.** Colours from their stylesheets or guidelines, each with a `use` and a `never`; fonts actually loaded on their site; voice: words they use, phrases they never use, and one off-brand / on-brand sentence pair. Mark guesses as guesses.
3. **Confirm.** Show the file. Set `"confirmed": true` only after the user agrees.
4. **Check work against it.**
   ```
   python3 scripts/brand.py check --brand brand.json --files src/styles src/pages
   python3 scripts/brand.py check --brand brand.json --snapshot .mstack/design-review/snapshot.json
   ```
   A snapshot comes from design-review's collector; if that skill is not installed, check the stylesheets and markup instead and say the rendered page was not seen.
5. **Decide each item with the user**: replace with a kit value, or add it to the kit on purpose.
6. **Report.** End state, off-kit colours, fonts and phrases with locations, and declared pairs under their contrast limit.

## Rules

- The brand is the user's. Never fill the file from taste or a template, and never confirm it for them.
- Neutral greys can be allowed as a group (`allow_neutrals`); say so in the report when they are.
- An off-kit value is a finding, not an automatic fix. The user decides whether the kit or the work changes.
- Checking with `--draft` is allowed before confirmation; the result says draft.

## Not for

- Contrast of all token pairs in light and dark → use `token-check`.
- Vague buttons and dead-end errors → use `ui-copy`.
- Building a new screen → use `ui-build`.

## Level

- beginner: explain each part of the brand file and why "never" rules matter.
- standard: as written.
- expert: the off-kit list and the end state. Confirmation and the check still apply.

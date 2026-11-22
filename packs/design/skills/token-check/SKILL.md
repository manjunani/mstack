---
name: token-check
description: Measures every text-on-background colour token pair in light and dark mode, proposes a passing value with the same hue for each failure, and lists hard-coded colours and off-scale sizes in the code. Use when the user asks if the palette or theme colours are readable, wants dark mode contrast checked, or asks to find colours and spacing that ignore the design tokens or CSS variables. Not for checking a rendered page (use design-review) or for brand rules (use brand-kit).
license: MIT
metadata:
  pack: design
  version: 0.1.0
  needs: python3
---

# Token check

Produces a contrast table for every token pair in each theme, one proposed fix per failing token, and a list of values in the source that bypass the tokens.

## Done when

- `scripts/tokens.py contrast` exits 0: every pair passes in each theme, or is waived with a reason.
- `scripts/tokens.py drift` exits 0: no hard-coded colour or off-scale size is left, or each is accepted with a reason.
- Both were run again after any change.

End in exactly one state: **pass**, **fail** (pairs or values listed), **not verified** (a pair could not be measured, say which and why), or **blocked** (no token file found; ask the user where the tokens live).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| Token files | CSS with custom properties on `:root`, a dark selector, or `@theme`; optionally `tailwind.config.*` | ask the user where tokens are defined; end as blocked |

## Steps

The script is `scripts/tokens.py` in this skill's folder.

1. **Find the tokens.** Search for files that define `--` custom properties and for a Tailwind config. List them.
2. **Measure.**
   ```
   python3 scripts/tokens.py contrast src/styles/tokens.css --tailwind tailwind.config.js
   ```
   Without `--pairs`, pairs are guessed from names (`--x-foreground` on `--x`, `--on-x` on `--x`, `--foreground` on `--background`). Show the guessed pairs to the user. If names follow no pattern, write a pairs file (`[{"text": "--ink", "background": "--paper", "large": false}]`) and pass `--pairs`.
3. **Read the failures.** Each failing token gets one proposed value that keeps its hue and passes on every background it is paired with. Lines marked `not measured` name a colour space or translucent background the script does not read; check those another way and say so.
4. **Find drift.**
   ```
   python3 scripts/tokens.py drift src --css src/styles/tokens.css
   ```
   Each hard-coded colour shows the nearest token; each off-scale size shows the nearest step.
5. **Propose, then change.** Show the proposed token values and the drift list. Change files only after the user agrees, then run both commands again.
6. **Report.** End state first; then failing pairs with ratio and limit, proposals, drift count by file, and what was not measured.

## Rules

- Fix at the token. One token change repairs every screen that uses it; patching one component does not.
- Waivers and accepted values need a reason (disabled state, legacy file with a removal date). The script refuses empty reasons.
- The limits live in `references/limits.json` with their source. They were written from memory and are marked unverified; say so if the user relies on them.
- Never change a pair's limit to make it pass. Large text gets the lower limit only when it really is large.

## Not for

- Contrast as drawn on a real page, through images and opacity → use `design-review`.
- Colours and fonts that are off the user's brand → use `brand-kit`.
- A full accessibility audit → use `a11y-audit`.

## Level

- beginner: explain what a contrast ratio is and why dark mode needs its own check.
- standard: as written.
- expert: the failing rows, proposals and counts only. Both commands still run.

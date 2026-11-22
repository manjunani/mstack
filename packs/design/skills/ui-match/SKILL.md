---
name: ui-match
description: Builds a screen from a screenshot, Figma export or mockup image and proves how close it is by comparing a screenshot of the result with the reference, region by region. Use when the user shares a design image or screenshot and says "build this screen from the screenshot", "make it look like this", "match this mockup" or "pixel perfect". Not for designing a screen with no reference (use ui-build) or for release checks of a page (use design-review).
license: MIT
metadata:
  pack: design
  version: 0.1.0
  needs: python3, a browser the agent can drive, the reference as PNG
---

# UI match

Produces the built screen, a region table of how far it is from the reference, a diff image, and a list of differences kept on purpose.

## Done when

- `scripts/compare_png.py compare` exits 0 on a screenshot taken at the reference's width, or every region still over the limit is listed with a reason in the regions file.
- No more than three rounds were used (`--record` counts them).

End in exactly one state: **pass**, **fail** (regions listed), **not verified** (the image could not be compared; say why), or **blocked** (three rounds used with differences left, or no way to render).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| Reference as 8-bit RGB or RGBA PNG, not interlaced | `python3 scripts/compare_png.py info ref.png` | ask for a PNG export at 1x or 2x; palette, greyscale, 16-bit, interlaced PNG and JPEG are refused |
| A browser to screenshot the build | host browser tool or Playwright | build anyway; end as not verified |

## Steps

The script is `scripts/compare_png.py` in this skill's folder.

1. **Check the reference.** `info ref.png`. Note its width; a 2x export is twice the CSS width.
2. **Read it into measurements.** Write down the layout grid, spacing steps, type sizes, colours and components. Map each to what the project already has (tokens, components) before writing new code.
3. **Build** in order: layout, then type and spacing, then colour. Add the states the image cannot show (hover, focus, empty, error) using the project's patterns.
4. **Screenshot** the page at the reference's CSS width, same scroll position, same content. Save it as PNG.
5. **Compare.**
   ```
   python3 scripts/compare_png.py compare ref.png shot-1.png --grid 6x8 --diff diff-1.png --record
   ```
   Open the diff image to see where pixels differ. For known regions use a regions file: `[{"name": "header", "x": 0, "y": 0, "width": 1440, "height": 80}]`.
6. **Fix and repeat**, three rounds at most. A difference kept on purpose (real data instead of mock text, the product's own font) gets `"ignore": true` and a reason in the regions file.
7. **Report.** End state, rounds used, the region table, and each kept difference with its reason.

## Rules

- A match is claimed only from a comparison the script ran. Looking at both images is not a comparison.
- Never lower the tolerance or raise the limit to get a pass without telling the user, and name the values used.
- Use the project's tokens and components even when the image is a few pixels off from them; list that as a kept difference.
- The defaults in `references/defaults.json` are mstack's first settings, not a standard.

## Not for

- A screen with no reference image → use `ui-build`.
- Gating a page for overflow, contrast and names → use `design-review`.

## Level

- beginner: explain the region table, the diff image and why widths have to match.
- standard: as written.
- expert: the table of failing regions and the end state. Comparison and round limit still apply.

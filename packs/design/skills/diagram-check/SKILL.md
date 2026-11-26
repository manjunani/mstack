---
name: diagram-check
description: Checks an SVG, draw.io or Mermaid diagram before it ships and lists each problem with element id and coordinates. Use when an architecture, flow or sequence diagram was drawn or exported and someone asks if it is ready to share, readable, or OK in dark mode. Finds overlapping boxes and labels, clipped or off-canvas text, low contrast, unlabelled shapes, arrows that touch nothing and tiny fonts. Not for charts drawn from data (use chart-check) or rendered web pages (use design-review).
license: MIT
metadata:
  pack: design
  version: 0.3.0
  needs: python3
---

# Diagram check

Produces a list of layout, readability and theme problems in one diagram file, each with the element's id and coordinates, ending in one state.

## Done when

- `scripts/diagram_check.py <file>` exits 0 on the file that will be shipped, or every remaining finding is accepted by the user with a reason.
- After any change to the diagram, the script was run again on the changed file.
- Every `not measured` line is named in the report as not verified.

End in exactly one state: **pass**, **fail** (findings listed), **not verified** (the script exited 2: say which items or checks could not run and why), or **blocked** (no diagram file found: ask the user for the path).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| The diagram file | `.svg` (also an exported `.drawio.svg`), `.drawio` or draw.io `.xml`, `.mmd` | ask the user which file; end as blocked |
| A rendered SVG, for Mermaid layout | the user's own export (for example mermaid-cli) | report layout as not verified; do not install anything |

## Steps

The script is `scripts/diagram_check.py` in this skill's folder. It only reads the file.

1. **Find the file.** Use the path the user gave. If they named a diagram but no path, search for `*.svg`, `*.drawio`, `*.mmd` and ask which one when there are several.
2. **Ask where it is shown, only if unclear.** A README or docs site can be dark: keep the default `--theme both`. If the user says it only appears on a white page, pass `--theme light`. If the SVG is displayed narrower than its own width (an `<img width=...>`), pass `--display-width <px>`.
3. **Run.**
   ```
   python3 scripts/diagram_check.py docs/architecture.svg
   ```
   Options: `--theme both|light|dark`, `--display-width 600`, `--min-font 11`, `--ignore 'grid-*'` (repeatable; skips elements by id or class glob, for a background grid or a decorative frame).
4. **Read the findings.** Each `FAIL` line has a rule, the element and its box as `(x,y wxh)` in the file's own units:
   - `overlap`, `clipped`, `off-canvas`: move or resize the named element; widen the box rather than shrink text under the minimum.
   - `contrast`: change the text or fill colour of that pair.
   - `theme`: the colour is fixed in the file and fails on a dark page. Offer one of: give the diagram its own opaque background, use `currentColor`, or add a `prefers-color-scheme: dark` rule.
   - `unlabelled`: add a label, or a `<title>` for an icon that needs none on screen.
   - `loose-edge`: extend the line to the shape it should reach, or attach the draw.io edge to a cell.
   - `small-font`: raise the size.
   Text widths are estimated from character counts, so a finding within a few pixels is worth a look in a viewer before changing anything.
5. **Read the `not measured` lines.** Rotated text, `<use>`, images, HTML labels and CSS the script cannot apply are listed there. For Mermaid source only style colours, font sizes and empty labels are checked; ask the user to export an SVG and run again for the layout.
6. **Propose, then change.** Show the findings and the proposed edits. Edit the diagram only after the user agrees; write to the same file only when it is their working copy under version control, otherwise to a new file. Run the script again.
7. **Report.** End state first; then the findings by rule with element and coordinates, what was changed, and what was not measured.

## Rules

- The result comes from the script's last line. Never call a diagram ready from looking at its source.
- `not verified` is never reported as a pass, including Mermaid source with no findings.
- Limits (4.5:1 and 3:1 contrast, 12 px minimum, gaps and the dark page colour) live in `references/limits.json`. All are marked unverified; say so if the user relies on them. Do not raise a limit to make a file pass.
- `--ignore` is for elements that are decoration by design. Say in the report which patterns were ignored and why.
- A warning (no `<title>` on the SVG) is advice, not a failure.

## Not for

- A chart made from data: axes, scales, misleading bars → use `chart-check`.
- A web page or app screen as rendered in a browser → use `design-review`.
- A full accessibility audit of a page → use `a11y-audit`.
- Colour tokens of a theme → use `token-check`.

## Level

- beginner: explain each rule in one line, what a contrast ratio is, and why a transparent diagram can vanish on a dark page.
- standard: as written.
- expert: the FAIL lines, not measured lines and end state only. The script still runs on every change.

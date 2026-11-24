---
name: design-review
description: Gates a rendered page before it is called done, from what the browser drew at phone, tablet and desktop width. Use when a page, screen or component was built or changed and someone asks "does it look right?", "is the UI done?" or wants it checked on mobile. Blocks on cut-off or overflowing content, low contrast, controls with no name, tiny tap targets and placeholder text, in each theme and state. Not for a full WCAG audit (use a11y-audit) or for reviewing code (use review).
license: MIT
metadata:
  pack: design
  version: 0.2.2
  needs: python3, a browser the agent can drive (host browser tool or Playwright)
---

# Design review

Produces a checked snapshot of the rendered page and a report that blocks on measurable defects and only warns on taste.

## Done when

- A snapshot exists with a view for every required width (320, 768 and 1440 px by default), every theme the product has, and every state the change touches.
- `scripts/check_page.py check` on that snapshot exits 0, or every remaining finding has a waiver with a reason.
- Every element the checker could not judge (text on an image or gradient) was looked at in a screenshot and either fixed or waived.

End in exactly one state: **pass**, **fail** (blocking findings listed), **not verified** (say which view, state or element was not judged), or **blocked** (no way to render the page; say what is needed).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| A browser the agent can drive | the host's browser tool can open a URL, or `node -e "require('playwright')"` works in the project | ask the user to open the page and paste the collector into the console; if that is not possible, end as blocked |
| A running page | the URL loads and shows the screen under review | ask for the URL or the start command; end as blocked |

## Steps

Scripts are in this skill's folder: `scripts/collect.js` (runs in the page) and `scripts/check_page.py`.

1. **Check needs.** Confirm the page loads at the URL and shows the right screen. A screenshot of the wrong state (signed out, empty, wrong role) proves nothing: name the state you expect and look for it first.
2. **List the views.** Widths 320, 768, 1440; each theme (light, dark); each state the change touches (default, empty, loading, error, long text). Write the list down.
3. **Capture each view.** Set the viewport, theme and state, label it, then evaluate the collector and save its result as one JSON file per view:
   ```
   window.__mstackView = { theme: 'dark', state: 'error' }   // in the page, before the collector
   ```
   With Playwright: `page.evaluate(fs.readFileSync('<skill>/scripts/collect.js', 'utf8'))`. With a host browser tool: run the file's text as JavaScript. The format is in `references/snapshot-format.md`; read it only if a capture looks wrong.
4. **Merge and check.**
   ```
   python3 scripts/check_page.py merge view-320.json view-768.json view-1440.json --out .mstack/design-review/snapshot.json
   python3 scripts/check_page.py check .mstack/design-review/snapshot.json --themes light,dark --states default,error
   ```
5. **Look at what the script cannot judge.** For each `CHECK` line, take a screenshot and look. If it reads clearly, add a waiver (`rule`, `selector`, `reason`) to a waivers file and pass it with `--waivers`. Also look once at each width yourself: the script does not know whether the layout is what was asked for.
6. **Fix and repeat.** Fix the blocking findings in the source, capture again, check again. Stop after three rounds and report what remains.
7. **Report.** End state first. Then per view: blocking findings, waivers with their reasons, warnings in one line, and what was not checked (focus, hover, motion, states not captured).

## Rules

- Contrast, clipping, overflow, missing names, small targets and placeholder text block. Generic-look warnings never block; mention them once and move on.
- A waiver needs a reason a reviewer can check ("looked at the 320 px screenshot: caption sits on a dark scrim"). "Fine" is not a reason.
- Never edit the snapshot to make a finding go away. Fix the page and capture again.
- Reading code is not a review. If the page could not be rendered, the result is blocked, not pass.

## Not for

- Every WCAG rule, a keyboard pass, screen-reader names in depth → use `a11y-audit`.
- Contrast of the design tokens themselves, without a page → use `token-check`.
- Reviewing the code change for bugs → use `review`.
- Checking a whole user journey works end to end → use `qa-run`.

## Level

- beginner: explain each rule the first time it appears and why it matters to people using the page.
- standard: as written.
- expert: report blocking findings and the end state only. Every view and check still runs.

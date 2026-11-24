---
name: a11y-audit
description: Finds accessibility failures on a rendered page with axe-core and a Tab-key walk, fixes them, then proves the fix by running the same scan against a saved baseline. Use when the user asks for an accessibility or WCAG audit, screen reader or keyboard support, says "can blind users use this", or a page failed an a11y check. Not for a visual check of layout and contrast before release (use design-review) or for colour tokens alone (use token-check).
license: MIT
metadata:
  pack: design
  version: 0.2.1
  needs: python3, node, Playwright with Chromium and axe-core in the project (or a host browser tool that can run axe)
---

# Accessibility audit

Produces an axe-core result and a keyboard log per page, a baseline saved before any fix, and a second run that shows what was fixed, what remains and what is new.

## Done when

- `scripts/audit.py check` exits 0 on the run after the fixes: zero violations at the chosen level (AA by default) on every page and state in the baseline, every focus stop shows focus, no trap, every focusable element reached.
- The comparison with the baseline shows the same pages and at least as many rules as before.
- The report lists what no scanner covers: screen reader output, whether alt text and labels are true, reading order.

End in exactly one state: **pass**, **fail** (violations listed), **not verified** (no keyboard log, results axe could not decide, or a narrower run than the baseline), or **blocked** (the scan cannot run; say what to install).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| node, Playwright, Chromium, axe-core | `python3 scripts/audit.py needs --root <project>` | print what it says to the user; nothing is installed by this skill; end as blocked |
| A running page | the URL loads | ask for the URL or start command; end as blocked |

## Steps

Scripts are in this skill's folder: `scripts/audit.py`, `scripts/run_axe.mjs`.

1. **Check needs.**
   ```
   python3 scripts/audit.py needs --root .
   ```
   If it ends as blocked and the host has a browser tool that can load the project's own `node_modules/axe-core/axe.min.js` into the page, use that instead and save `axe.run()` output as JSON. Otherwise stop and tell the user what to add.
2. **List pages and states.** Every page the user named, plus open dialogs, menus and error states on them.
3. **Scan and walk.** From the project folder:
   ```
   node <skill>/scripts/run_axe.mjs --url http://localhost:3000/ --url http://localhost:3000/cart --out .mstack/a11y-audit/run-1
   ```
   It writes `axe.json` and `keyboard.json`. For dialogs, also check by hand that Escape closes them and focus stays inside while open; add each result as a `checks` entry in the keyboard log.
4. **Save the baseline.**
   ```
   python3 scripts/audit.py check --axe .mstack/a11y-audit/run-1/axe.json --keyboard .mstack/a11y-audit/run-1/keyboard.json --save-baseline
   ```
5. **Fix in source.** One cause at a time; prefer the native element (a real `<button>`, a `<label>`) over ARIA added on top.
6. **Scan again into a new folder and compare.**
   ```
   python3 scripts/audit.py check --axe .mstack/a11y-audit/run-2/axe.json --keyboard .mstack/a11y-audit/run-2/keyboard.json --baseline
   ```
   For each `LOOK` line (axe could not decide), look at the element and record it in a reviewed file passed with `--reviewed`.
7. **Report.** End state first, then fixed / remaining / new, then what no scanner covers.

## Rules

- A source scan is not an audit. If nothing could render the page, the result is blocked.
- A focus stop marked not visible may use a ring the script cannot see (a pseudo-element). Look at it; do not just mark it fine.
- Never disable an axe rule, lower the level or drop a page to get a pass. The baseline comparison flags a narrower run.
- axe-core is used from the user's project. Do not copy it into this skill.

## Not for

- A release check of layout, overflow and contrast at several widths → use `design-review`.
- Contrast of colour tokens without a page → use `token-check`.
- The words on buttons and errors → use `ui-copy`.

## Level

- beginner: explain each failing rule in plain words and who it affects.
- standard: as written.
- expert: the fixed / remaining / new table and the end state. Every scan still runs.

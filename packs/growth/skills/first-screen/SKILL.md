---
name: first-screen
description: Reports what a landing page puts first: the first heading, first paragraph, first call to action and where it leads, whether the headline names the product, whether promised words appear, and the bytes that load first. Use when a visitor lands and leaves, an ad or post promises something, or someone asks "does the hero say what we do". Not for checking layout at real screen sizes (use design-review).
license: MIT
metadata:
  pack: growth
  version: 0.1.0
  needs: python3; network only for a URL
---

# First screen

Produces the first heading, paragraph and call to action of a page as read from its HTML, with checks on each.

## Done when

- `scripts/firstscreen.py` ran on the page the visitor really lands on and ended with a `RESULT` line.
- If the visitor was promised something (ad, post, listing), the promise was passed word for word with `--promise`.
- The reply says the result rests on HTML in document order, and that what truly shows before scrolling needs a browser.

End in exactly one state: **pass**, **fail** (no heading or call to action, an action that leads nowhere, none of the promised words), **not verified** (page built by script, a button whose target a script sets), or **blocked** (page unreadable).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| The landing page | a file or address the user gave | ask which page visitors land on; end as blocked |
| A browser (optional) | the host's own browser tool | without one, say the screen itself was not seen |

## Steps

The script is `scripts/firstscreen.py` in this skill's folder; in Claude Code `"${CLAUDE_SKILL_DIR}/scripts/firstscreen.py"`.

1. **Write down the promise** the visitor saw before clicking, in the user's exact words.
2. **Run.**
   ```
   python3 scripts/firstscreen.py https://their-site.tld/ --promise "<the words>"
   python3 scripts/firstscreen.py saved/index.html --root saved
   ```
3. **Read the output.** A headline sharing no word with the title or description is a warning: it may not say what the product is. Load size over the guidance in `references/budget.json` is a warning, not a fail.
4. **If a browser is available**, open the page at phone width, wait a few seconds for banners, take a screenshot, and compare it with the script's heading and action. Say which basis the report rests on.
5. **Report.** End state first, then the three firsts quoted, then findings, then not checked (real screen, taste, load time).

## Rules

- Whether the words persuade is taste: a warning the user may ignore, never a fail.
- No fake urgency, countdowns, invented user counts or testimonials are suggested as fixes.
- Suggest a headline only from words the user's own product text supports.

## Not for

- How the page renders at each width and theme → use `design-review`.
- Load time on a real connection → use `page-speed`.
- Wording of buttons and errors inside an app → use `ui-copy`.

## Level

- beginner: explain why the first heading and action matter to a visitor who will not scroll.
- standard: as written.
- expert: the three firsts and the end state only. Every check still runs.

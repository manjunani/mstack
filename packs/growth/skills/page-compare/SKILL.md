---
name: page-compare
description: Sets two saved HTML pages side by side on measurable points only, with no verdict on which is better. Use when someone wants our landing page compared with a competitor's page. Counts title, headings, words, calls to action, structured data types, image alt coverage and HTML size, and fails on sentences copied word for word. Not for auditing a whole site (use site-audit).
license: MIT
metadata:
  pack: growth
  version: 0.2.0
  needs: python3
---

# Page compare

Produces a two-column table of counts for two saved pages, and a list of any sentences they share word for word.

## Done when

- Both pages were saved to files and `scripts/compare.py` ran on them with a `RESULT` line.
- The reply shows the table as printed and states no verdict on which page is better.
- Sentences shared word for word are listed, or the reply says there are none.

End in exactly one state: **pass** (table complete), **fail** (copied sentences), **not verified** (a page built by script, so its counts describe an empty shell), or **blocked** (a file missing, not HTML, or the same file twice).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| Both pages saved as HTML | the two files exist | ask the user to save them (browser "Save page as", or the rendered HTML); end as blocked |

## Steps

The script is `scripts/compare.py` in this skill's folder; in Claude Code `"${CLAUDE_SKILL_DIR}/scripts/compare.py"`.

1. **Save both pages** to files. For pages built by script, save the rendered page, not the source.
2. **Run.**
   ```
   python3 scripts/compare.py ours.html theirs.html --out .mstack/growth/compare-<date>.json
   ```
3. **Read the table.** Differences are facts (their page has two h1, ours has none of their JSON-LD types). Say what differs; leave the meaning to the user.
4. **Report.** End state first, then the table, then shared sentences if any, then not checked (which is better, ranking, conversion, assets beyond the HTML).

## Rules

- Never say which page is better, ranks higher or converts more. The script measures; it does not judge.
- Never copy, paraphrase closely or "borrow" the competitor's text, claims or testimonials. Copied sentences fail.
- Fetch other people's pages only by the user's own saving; this skill does not crawl them.

## Not for

- An SEO audit of a whole site → use `site-audit`.
- What our own page puts first → use `first-screen`.
- How a page looks at each width → use `design-review`.

## Level

- beginner: explain what each row of the table measures.
- standard: as written.
- expert: the table and end state only. Every measure still runs.

---
name: launch-site-check
description: Asks a site for every page a first visitor needs before launch (home, pricing, privacy, terms, contact, a real 404, favicon, social preview image tags, a working sign-up or download link) and reports each one. Use when a product or landing site is about to go live, someone asks "are we ready to launch" or "is anything missing from the site". Not for status, headers and certificates of a deployment (use site-check).
license: MIT
metadata:
  pack: growth
  version: 0.1.0
  needs: python3, network access to the site named
---

# Launch site check

Produces one line per required page or tag: answers and holds text, missing, or not checked.

## Done when

- `scripts/launch.py` ran against the real base address and ended with a `RESULT` line.
- Every required item has a line: home, not-found, pricing, privacy, terms, contact, favicon, preview, action, robots.
- Pages the product truly does not have were left out with `--skip` and are listed as not checked, by the user's choice.

End in exactly one state: **pass**, **fail** (an item missing or broken, shown), **not verified** (something on another host, a page built by script, a form not submitted), or **blocked** (no real address, the site unreachable).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| The site's base address | the user named it (staging is fine) | ask for it; end as blocked |

## Steps

The script is `scripts/launch.py` in this skill's folder; in Claude Code `"${CLAUDE_SKILL_DIR}/scripts/launch.py"`.

1. **Ask what the product has.** No pricing page for a free tool? Use `--skip pricing`. A page at an unusual path? Use `--path privacy=/legal/privacy-notice/`. Sign-up worded oddly? Use `--action-text "join the waitlist"`.
2. **Run.**
   ```
   python3 scripts/launch.py https://their-site.tld --out .mstack/growth/launch-<date>.json
   ```
3. **Read the output.** A made-up address that answers 200 is a fail: missing pages then look present to crawlers. A page found only at a usual path, not linked from the home page, is reported that way.
4. **Fix and re-run** until every line is ok or a deliberate skip.
5. **Report.** End state first, then each failing item with its address and what it gave, then the fine items, then not checked (forms were not submitted, other hosts were not asked).

## Rules

- Forms are never submitted and no account is created by this skill.
- A privacy or terms page that exists is not a legal review; say so if asked.
- Placeholder text ("lorem ipsum") on the home page blocks the launch.
- Preview tags need full addresses; a relative og:image is a failure.

## Not for

- Certificate, redirects and security headers → use `site-check`.
- Every link on every page → use `link-check`.
- Titles and headings across the whole site → use `site-audit`.
- How the pages look → use `design-review`.

## Level

- beginner: say why each item matters to a first visitor or to sharing.
- standard: as written.
- expert: failing lines and the end state only. Every item is still checked.

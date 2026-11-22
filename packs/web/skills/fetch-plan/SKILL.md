---
name: fetch-plan
description: Writes a plan before fetching many pages: robots.txt verdict per address, crawl delay, sitemap, terms link, count, rate and duration; refuses a plan that touches disallowed paths. Use when the user wants to scrape, crawl, download or collect many pages or a list of URLs, asks "can I crawl this site?" or "is it ok to scrape this", or wants to grab every page of a kind. Not for reading one page (use page-extract) or checking links (use link-check).
license: MIT
metadata:
  pack: web
  version: 0.1.0
  needs: python3
---

# Fetch plan

Produces a plan file under `.mstack/fetch-plan/` that a later fetch follows: which addresses, which pause per host, how long, and who read the terms.

## Done when

- `scripts/fetch_plan.py` printed `RESULT pass` with a plan file, or ended fail, not verified or blocked with its reason.
- No address in the plan is disallowed by robots.txt, and none is unknown.
- The terms of use were read by a person, and the plan records who, when and what they allow.

End in exactly one state: **pass** (plan ready), **fail** (disallowed addresses; no plan), **not verified** (robots.txt unreadable), or **blocked** (terms not reviewed, bad input, list too long).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| The list of addresses | arguments or a file, one per line | ask the user; do not invent paths |
| A person who read the site's terms | the user says so | the plan stays a draft; end as blocked |

## Steps

The script is `scripts/fetch_plan.py` in this skill's folder.

1. **Collect the addresses** into a file. If the site has a sitemap or an API, prefer it over guessing pages.
2. **Make a draft plan.**
   ```
   python3 scripts/fetch_plan.py --urls pages.txt
   ```
   It requests robots.txt once per site and the front page once to look for a terms link. It fetches none of the listed pages.
3. **If it fails on disallowed addresses,** show them. The user may drop them (`--drop-disallowed`); there is no option to ignore robots.txt and none must be improvised.
4. **Ask the user to read the terms** at the link the plan shows (or find them). Do not read them for the user and declare them fine.
5. **Finish the plan** with the user's own words:
   ```
   python3 scripts/fetch_plan.py --urls pages.txt --terms-reviewed "Sam read example.org/terms on 2026-11-22: personal research use allowed"
   ```
6. **Report.** End state, count, pause per host, estimated duration, what was left out, the plan file path. The fetch itself then uses the plan's user agent and pauses.

## Rules

- Not allowed in this pack: scraping behind a login, getting around rate limits or blocks, rotating identities or user agents, ignoring robots rules, collecting personal data about people. Refuse, and say which one.
- The pause is never shorter than the site's Crawl-delay or one second for a public host.
- A 429 or a block during the fetch ends that host; report it rather than retrying.
- `--max-pages` (default 200) stops oversized lists; raising it is the user's call.

## Not for

- Reading one page the user named → use `page-extract`.
- Finding broken links on a site → use `link-check`.
- Testing an API's responses → use `api-check`.

## Level

- beginner: explain robots.txt, crawl delay and why terms matter.
- standard: as written.
- expert: the plan summary and the end state. The robots check and the terms question are never skipped.

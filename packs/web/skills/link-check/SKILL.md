---
name: link-check
description: Finds broken links and missing images, scripts and styles on one site by crawling it within a stated depth and page limit, and sorts every target into broken, fine and could not check. Use when the user asks "any dead links?", "are there 404s on the site", "did the move break anything", or before launching or after restructuring pages. Not for one address's headers or certificate (use site-check) or for a search-engine audit (use site-audit).
license: MIT
metadata:
  pack: web
  version: 0.2.0
  needs: python3
---

# Link check

Produces three lists for one site (broken, fine, could not check) and a report file with the crawl's scope.

## Done when

- `scripts/link_check.py` finished and printed its scope line and `RESULT` line.
- One example from each kind of broken item (link, asset) was opened again by hand and the failure confirmed.
- The reply states the scope (pages read of pages found, the limits) and the could-not-check count with its reasons.

End in exactly one state: **pass** (nothing broken, nothing unchecked), **fail** (something broken), **not verified** (some targets could not be checked), or **blocked** (robots.txt forbids the crawl, bad address).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| A start address on the user's site, or one they may crawl | the user named it | ask; never pick a site yourself |

## Steps

The script is `scripts/link_check.py` in this skill's folder.

1. **Check needs.** Ask the depth and page limit if the site is large; the defaults are depth 2 and 50 pages.
2. **Crawl.**
   ```
   python3 scripts/link_check.py https://example.org/
   python3 scripts/link_check.py https://example.org/docs/ --depth 3 --max-pages 120
   python3 scripts/link_check.py http://127.0.0.1:8000/ --delay 0 --no-external
   ```
   It reads robots.txt first and keeps any crawl delay. Pages on the site are read with GET; other targets get one HEAD each; external links get one HEAD each after that host's robots.txt, at most one request per second per public host.
3. **Read the three lists.** Only "fine" means it answered 2xx. "Could not check" is not fine: each line says why (robots, a 403, a timeout, a limit).
4. **Confirm one example** of each broken kind by running `scripts/link_check.py` on the page that links to it with `--depth 0`, or by opening the target.
5. **Read the notes.** A site that answers 200 for a made-up address hides missing pages; a page with many scripts and few links builds its links in the browser, and this crawl cannot see them.
6. **Report.** End state, scope, broken items with the page that links to each, the could-not-check reasons grouped, the report file path.

## Rules

- Stay on one site. Never raise the rate above what the site's robots.txt asks; `--delay` can only slow down a public host, never go below one second.
- A host that answers 429 or 503 with Retry-After gets no more requests in this run. Report it; do not run again at once.
- No crawling behind a login, no cookies, no rotating identity or user agent. A 401 or 403 is listed as could not check.
- A broken external link may be the other site's temporary fault; say so before calling it the user's bug.

## Not for

- Headers, redirects and certificate of one address → use `site-check`.
- Titles, headings and sitemap coverage for search → use `site-audit`.
- Testing a user flow in a running app → use `qa-run`.

## Level

- beginner: explain the three lists and why "could not check" is not "fine".
- standard: as written.
- expert: the scope line, the broken list and the end state. The example check still happens.

---
name: page-speed
description: Measures how a page transfers without a browser: median time to first byte, bytes, requests, uncompressed text and missing cache headers, against the user's budgets. Use when the user asks "why is the page slow", "how heavy is it", "is gzip on", or wants a byte or request budget checked. States that rendering metrics are not measured. Not for a design review (use design-review) or post-deploy health (use deploy-check).
license: MIT
metadata:
  pack: web
  version: 0.3.1
  needs: python3
---

# Page speed

Produces transfer measurements for one page and a clear line that rendering was not measured.

## Done when

- `scripts/page_speed.py` ran with the user's budgets (if any) and printed its `RESULT` line.
- The reply names each failed check with its number, and says rendering metrics (largest paint, layout shift, interaction delay) were not measured.
- If the user wants those, the host's browser performance tool was used or the reply says it is not available.

End in exactly one state: **pass** (only with `--transfer-only`), **fail** (a finding or a budget exceeded), **not verified** (rendering not measured, which is the normal end; or assets that could not be measured), or **blocked** (bad input).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| A browser performance tool | only for rendering metrics | say they were not measured |

## Steps

The script is `scripts/page_speed.py` in this skill's folder.

1. **Ask for budgets** if the user has them (bytes, requests, first byte). Without them, only clear faults fail.
2. **Measure.**
   ```
   python3 scripts/page_speed.py https://example.org/ --runs 5
   python3 scripts/page_speed.py https://example.org/ --budget-bytes 800000 --budget-requests 40 --budget-ttfb-ms 400
   python3 scripts/page_speed.py http://127.0.0.1:3000/ --delay 0 --transfer-only
   ```
   The document is fetched `--runs` times and the median is reported; each listed asset once, after its host's robots.txt.
3. **Read the findings.** Uncompressed text over the limit and assets with no cache headers fail; an asset that only has ETag warns. The default first-byte limit is marked unverified in `references/budgets.json` and only warns.
4. **Say what the numbers are.** Lab numbers from this machine, one new connection per request, assets fetched one after another: not a visitor's load time.
5. **Report.** End state, first byte median and spread, bytes and requests, findings, what was not measured.

## Rules

- Never estimate or invent a rendering score. If no browser tool ran, rendering is not verified.
- A pass is possible only with `--transfer-only`, which means the user asked about transfer alone.
- Run against the production build or the deployed page; a dev server's numbers say little.
- No hammering: runs are capped at 10 and requests are paced per host.

## Not for

- Visual quality and layout of a page → use `design-review`.
- Whether a deploy is serving and healthy → use `deploy-check`.
- Headers and certificate of an address → use `site-check`.

## Level

- beginner: explain first byte, compression and caching in one sentence each.
- standard: as written.
- expert: the numbers, findings and end state. The rendering statement is never dropped.

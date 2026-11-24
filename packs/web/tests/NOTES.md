# mstack-web: what was tested and what was not

Date: 2026-11-22. Machine: macOS, Python 3.14, OpenSSL 4.1 (used only by the tests, to make throwaway certificates).

## How the script tests run

```
python3 packs/web/tests/scripts/run_cases.py --work .testrun/<new-folder>
python3 packs/web/tests/scripts/run_cases.py --work .testrun/<new-folder> --only link-check --show
```

`fixture_server.py` starts Python `http.server` instances on 127.0.0.1 only, serving pages written by
`cases_net.py`. Nothing touches the public internet. Every request is logged by the server, so the tests
prove what was *not* requested (disallowed paths, retries after 429, external hosts with `--no-external`).
`cases_text.py` covers the two skills that read local files only. Each case states its expected exit code
and the text the output must contain; the runner also checks the last line is the matching `RESULT` or `blocked:`.

Last full runs (2026-11-22): 163 cases, 163 as expected, 0 skipped, on three consecutive runs after the
pacing fix below. Every one of the 308 requests the servers saw carried the honest `mstack-web/0.1 (<script>; +repo)`
user agent, and the six copies of `webfetch.py` are byte-identical (both checked by the runner).

## Faults the tests caught (fixed)

- link-check: crawl delay measured from the start of the previous request, so a slow answer let the next
  request arrive 0.07 s after it under a 0.2 s Crawl-delay (seen once in four runs). The pause now counts from the end of each answer.
- cite-check: a quote whose source had inner quote marks ("four percent" - ...) was reported not found. Quote marks are now ignored when matching.
- page-watch: two looks in the same second gave the same snapshot name, so the change was compared against itself. Names now get a suffix.
- page-extract: nested `<div>` inside `role="navigation"` closed the navigation early and leaked its text; `<header>` inside `<article>` was dropped as page chrome. Both fixed.
- fetch-plan: a bad address ended without a `blocked:` last line.

## Per skill

| Skill | Cases | Tested | Not tested, and why |
|---|---|---|---|
| site-check | 28 | redirect hops, loop, >2 hops, 404/500, expected status, missing and wrong headers, `--require`, HSTS max-age, https downgrade, mixed content (active fails, passive warns), untrusted, 3-day and 20-day certificates against local HTTPS with `--ca-file`, refused connection, timeout, bad addresses, JSON report | certificate chain detail and hostname mismatch on a real public CA; IPv6; HTTP/2-only servers (urllib speaks HTTP/1.1) |
| link-check | 20 | three lists, robots disallow on own and external host, Crawl-delay kept (timed from server log), depth and page limits, request limit, `--no-external` sends nothing, HEAD-refused external is "could not check", soft-404 probe, start-redirect to another host, robots group naming `mstack-web`, robots 500, 429 stops the host, script-built page note, public page linking to 127.0.0.1 not followed | real public sites; `--max-minutes`; very large sites; links inside CSS/JS (stated as not checked) |
| page-extract | 25 | title, main text without nav/header/footer/aside/script/style, headings, links, tables into JSON; nested chrome; latin-1 and gzip; redirect; `--expect`, `--min-tables`; JavaScript-only page; near-empty; sign-in page; 403 and 429 requested once only; 404/500; PDF; timeout; saved file with no network; text aimed at an assistant flagged | pages over 5 MB; unusual encodings beyond latin-1/utf-8; real-world readability quality on varied sites |
| cite-check | 12 | spacing, curly quotes, dashes, ellipsis, HTML and page-extract JSON sources, index.json by key and address, blockquote with reference after, not found with closest match, source missing, letter case, claims file with all five verdicts and malformed entries, bad inputs | footnote-style references far from the quote; very long documents; PDFs (must be saved as text first) |
| fetch-plan | 20 | allowed/disallowed/unknown, longest-match with `*` and `$` (saved robots.txt, no network), Crawl-delay vs `--delay`, refusal on disallowed, `--drop-disallowed`, terms draft vs ready, two hosts, robots 404/403/503, group naming `mstack-web`, list file, limits, only robots.txt and front page requested | real sites' terms pages (the link finder is a keyword heuristic); sitemap contents are not read, only named |
| web-research | 13 | the notes checker: labels, sources, quoted without quote, inference without basis, single-source conclusion fails or warns when stated, bad dates, unknown claim refs, missing saved files | the research itself (search and fetch) is done by the host's tools and was not run here; quote truth is cite-check's job |
| page-speed | 20 | median first byte of N runs, bytes and requests, srcset not fetched, redirect counted, uncompressed script and document, no cache headers fails, ETag-only warns, missing asset, byte/request/first-byte budgets, unverified default only warns, robots-disallowed assets not fetched, asset limit, 429 stops the host, rendering always "not verified" unless `--transfer-only` | rendering metrics (needs a browser; not measured by design); keep-alive or HTTP/2 timing; real network latency |
| page-watch | 23 | first snapshot, pause between looks (no request sent), unchanged, script/spacing-only change ignored, added/removed lines and diff file, noise by id/class/line pattern, rules saved and reused, earlier page re-read with new rules, `--clear-ignores`, 500 and 403 keep the old snapshot, empty page, plain text, bad regex, `list` | scheduling (not the skill's job); pages that change their HTML structure heavily (diff stays line-based) |

## Trigger, silence and benefit tests

`tests/<skill>.json` holds 10 fire, 10 quiet (at least five near misses each) and 2 tasks per skill. They were
**not run**: `claude plugin eval` was out of scope for this build. Results are "not tested" until that run.
The task prompts that serve local sites need their fixture folders (`./site`, `./pages` and so on) prepared by the eval setup; that setup does not exist yet.

## Numbers that are not verified

`site-check/references/checks.json` and `page-speed/references/budgets.json` hold every threshold, all marked
`"verified": false` (written from memory or chosen by mstack). Both scripts print a note saying so. The page-speed
first-byte default only warns for that reason.

## Open points

- `webfetch.py` is copied into each fetching skill's `scripts/` (a skill may not depend on another's files); the runner checks the copies are identical. A change must be copied to all six.
- `page-speed` is listed as shared with another pack in docs/SKILLS.md; this build put it in web as asked.

## 2026-11-24: trigger prompts made concrete

Some fitting requests named no page, site or platform ("pull the table from this page", "find icon buttons
with no accessibility label"). In the test sessions the model asked which page, or could not tell an iOS app
from a web page, and stopped before any skill could start. Those requests now carry what a real request has:
an example.test address, a urls.txt file, or "my SwiftUI app". The near-miss requests are unchanged. Results
recorded before this date used the old wording.

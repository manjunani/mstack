# mstack-growth: test notes

Date: 2026-11-22. Built from `research/growth.md` section 6 and the mstack-growth list in `docs/SKILLS.md`.

## How to repeat the script tests

```
python3 packs/growth/tests/scripts/growth_cases.py            # all skills
python3 packs/growth/tests/scripts/growth_cases.py --only post-check --show
```

`growth_cases.py` writes the pages and files in `fixtures.py` (an invented product, "Tidepool") into a new folder
under `.testrun/`, starts five `http.server` instances on 127.0.0.1 (a clean site, a site with planted faults, a
site closed by robots.txt, a page built by script, and a server that answers 200 for every path), runs each case
and checks the exit code, required and forbidden output, and that the last line is a `RESULT` or `blocked` line.
It also checks that the closed site was asked only for robots.txt, that every request carried the checker's user
agent, that the shared copies of `pagefacts.py` and `claims.py` are identical, and that no input file changed.

Last run: 96 cases, 0 failed, 114 requests, all to 127.0.0.1. Nothing on the public internet was contacted.

## Shared code

`pagefacts.py` (HTML parser, polite fetch, report format) ships as an identical copy in site-audit,
structured-data-check, launch-site-check, first-screen and page-compare; `claims.py` ships in claim-check and
store-listing-check. A skill does not reach into another skill's folder. The test fails if the copies differ.

## Per skill

| Skill | Tested (exit code) | Not tested |
|---|---|---|
| site-audit | clean site (0); page limit cuts crawl (2); planted faults: no h1, 404 link, noindex in sitemap, sitemap 404 and foreign host, long title, missing description, two h1, heading order, missing alt, missing lang, duplicate titles, no canonical (1); robots closes site, only robots.txt requested (1); script-built page (2); placeholder host, unreachable host, existing report file (2); pagefacts on URL (0) and missing file (2) | sitemap index files and gzip sitemaps; Crawl-delay handling; redirect chains; `--max-seconds` cut-off; a real public site |
| structured-data-check | valid Product, BreadcrumbList, FAQPage in @graph (0); valid block by URL (0); parse error, missing name, missing offers/review/rating, no @context, FAQ without answer, rating and question not visible (1); no JSON-LD is a pass with reason (0); unknown type listed as not checked (0); microdata only (2); script-built (2); missing file (2) | the property lists themselves against Google's docs (all `verified: false`); RDFa |
| launch-site-check | ready site (0); unready site: lorem ipsum, missing pages, favicon 404, no preview tags, dead sign-up link (1); soft 404 server (1); wrong `--path` (1); `--skip` (0); script-built home (1); bad `--skip` name, placeholder host, unreachable (2) | HTTPS hosts; og:image on another host; mailto contact links; forms (never submitted by design) |
| post-check | X post with link counted as 23 (0); over 280 (1); same text on Mastodon (0); `[unverified]` marker (1); hashtag warning on LinkedIn (0); `--need-link` (1); blog front matter and image (0); missing description, bad date, missing image, TODO (1); remote image (2); empty draft, unknown platform, missing draft (2); `--list` (0) | grapheme counting on Bluesky with real emoji sequences (only an approximation is implemented); every limit (all `verified: false`) |
| claim-check | find: 4 claims (2) and none (0); all sourced (0); wrong quote, missing file, no entry, testimonial without permission (1); web evidence without `--fetch` (2) and with `--fetch` against the local server (0); template written (2) then rejected unfilled (1); missing files (2) | claims in HTML input beyond simple tag stripping; non-English text; how many real sentences are flagged by mistake |
| first-screen | saved file with `--root` (0); fetched page with kept promise (0); broken promise (1); vague headline warning plus dead action (1); button with script-set target (2); script-built (2); missing file (2) | anything a browser renders (layout, fonts, popups); `--root` missing for absolute paths |
| tracking-check | HAR with expected events (0); doubled event (1); email in URL masked in output, wrong property (1); no request to endpoint (1); status 0 (1); JSON batch body (0); plain address list (0); empty HAR (2); missing expected file (2) | real HAR exports from Chrome, Firefox and Safari; form-encoded multi-line bodies from real vendors |
| store-listing-check | clean Apple listing (0); long name, repeated keyword, missing screenshot, unsourced claims in three fields, TODO, padded commas (1); Google listing below screenshot minimum (1); claim without sources file (1) and with one (0); unknown store, missing file (2) | live store pages; screenshot pixel sizes; localised listings; every limit (all `verified: false`) |
| page-compare | two different pages (0, and output never says "better than"); copied sentences (1); script-built page (2); same file twice, URL instead of file, missing file (2) | pages saved with assets; non-English text |
| mail-domain-check | sound SPF, DMARC and 2048-bit DKIM split across two strings (0); `+all`, /4 range, p=none, 512-bit key (1); p=none fails, missing DKIM selector record (1); no selector (2); missing DMARC (1); two SPF records, bad p, pct, rua form, empty p= (1); junk file, no mode, not a domain, reserved name with `--lookup` (2); `--lookup` with no dig or nslookup on PATH (2) | a live `--lookup` (not run, by the build rules); nslookup output parsing; ed25519 keys; lookups inside include: records (listed as not checked by the script) |

The DKIM keys in the fixtures have the right DER shape and size but are not real key pairs.

## Not run

- Trigger, silence and benefit tests (`claude plugin eval`): not run, by the build rules (cost and shared files).
  `tests/<skill>.json` holds 10 fire, 10 quiet and 2 tasks per skill, ready for that run.
- `tools/build_map.py`: not run, by the build rules.

## Reference values

Every number in `references/*.json` was written from memory on 2026-11-22 and is marked `"verified": false`.
The scripts print a line saying so each run. They have to be checked against the named sources before anyone
relies on a pass near a limit.

## Names

No name from `docs/SKILLS.md` was changed. `page-speed` is not in this pack; the skills point to the web pack's
`page-speed`, as the list says one home is chosen and the build brief placed it in web.

## Benefit-test fixtures (2026-11-23)

- first-screen `promise`, launch-site-check `ready-check` and `no-pricing`, site-audit `audit-local-site`: the prompt said a site was already running on 127.0.0.1:8000, which an empty eval workspace cannot have. Each now ships a `site/` fixture and asks the agent to serve it on its own port (8783, 8781, 8782, 8784). Meaning unchanged.

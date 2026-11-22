---
name: page-watch
description: Tells what changed on one web page since the last look: saves a normalised text snapshot under .mstack/ and on the next run lists added and removed lines, ignoring parts the user marks as noisy (clocks, ads, counters). Use when the user asks "has this page changed", "tell me if the pricing page changes", "what's different on the docs since last week", or wants to track a policy or status page. Not for checking a site's headers (use site-check) or broken links (use link-check).
license: MIT
metadata:
  pack: web
  version: 0.1.0
  needs: python3
---

# Page watch

Produces a dated snapshot per look and, when the text changed, the added and removed lines and a saved diff.

## Done when

- `scripts/page_watch.py check` ran and printed its `RESULT` line.
- On a change, the reply quotes the added and removed lines and gives the diff file path.
- If noise caused the change, the noisy part was marked and the check rerun, and the user saw which rule was added.

End in exactly one state: **pass** (no change), **fail** (the page changed; here this means changed, not broken), **not verified** (first snapshot, no answer, an error page), or **blocked** (too soon after the last look, refusal, bad input).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| Something that runs it again later | the host's scheduler, or the user | say the skill only looks when run |

## Steps

The script is `scripts/page_watch.py` in this skill's folder.

1. **First look** saves the baseline and ends as not verified (nothing to compare yet).
   ```
   python3 scripts/page_watch.py check https://example.org/pricing
   ```
2. **Later looks** compare with the last snapshot.
3. **If the change is noise** (a clock, a counter, a rotating banner), mark it and look again:
   ```
   python3 scripts/page_watch.py check https://example.org/pricing --ignore-id clock --ignore-class banner --ignore-line "^Updated \d+ minutes ago$" --min-interval 0
   ```
   Rules are saved with the page. The earlier page is read again with the new rules, so a rule change is never reported as a page change.
4. **`list`** shows every watched page with its last look and last change.
5. **Report.** End state, added and removed lines, diff path, rules in force.

## Rules

- One request per look; the script refuses a second look within `--min-interval` seconds (default 60). Scheduling is not this skill's job; suggest a sensible interval (hours, not seconds).
- An error page or a refusal is never saved as a snapshot; the earlier one stays.
- No sign-in, no getting around blocks or rate limits, no watching pages to track people.
- Snapshots stay in `.mstack/page-watch/`, which the script lists in `.mstack/.gitignore`.

## Not for

- Headers, redirects or certificate of an address → use `site-check`.
- Broken links across a site → use `link-check`.
- Turning a page into structured data → use `page-extract`.

## Level

- beginner: explain snapshots and noise rules.
- standard: as written.
- expert: the added and removed lines and the end state.

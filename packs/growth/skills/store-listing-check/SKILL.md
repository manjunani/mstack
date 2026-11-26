---
name: store-listing-check
description: Checks an app store listing kept as a file (name, subtitle, description, keywords, screenshots) against the store's field limits from a dated list, finds repeated keywords and missing screenshots, and fails claims with no source. Use when App Store or Google Play listing text is written or changed, or someone asks if the store description and keywords fit. Not for build, privacy manifest and submission readiness (use ios-submit-check).
license: MIT
metadata:
  pack: growth
  version: 0.3.0
  needs: python3
---

# Store listing check

Produces one line per listing field: within its limit, over it, empty, or not checked, plus the claims that need a source.

## Done when

- The listing is in a JSON file (see `--help` for the fields) and `scripts/listing.py` ran on it with a `RESULT` line.
- Every number, superlative, comparison or quote in the text has an entry in a sources file, or was removed.
- The reply repeats that the limits are unverified and have to be checked in the store's console before submitting.

End in exactly one state: **pass**, **fail** (a field over its limit or empty, repeated keywords, a missing screenshot file, an unsourced claim), **not verified** (remote screenshots, unopened evidence), or **blocked** (no listing file, unknown store).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| The listing as JSON | the file exists and names `"store": "apple"` or `"google"` | write it with the user to a new file under `.mstack/growth/` |

## Steps

The script is `scripts/listing.py` in this skill's folder; in Claude Code `"${CLAUDE_SKILL_DIR}/scripts/listing.py"`.

1. **Put the listing in a file**, one per store and language.
2. **Run.**
   ```
   python3 scripts/listing.py .mstack/growth/listing-en.json
   python3 scripts/listing.py .mstack/growth/listing-en.json --sources .mstack/growth/sources.json
   ```
   The sources file uses the same format as `claim-check`.
3. **Read the output.** Failures block submission. Warnings (keywords already in the name, plural pairs, spaces after commas) cost characters but are the user's call.
4. **Fix in a new file**, keeping the original, and run again.
5. **Report.** End state first, then each failing field with its count and limit, then fine fields, then not checked (live store page, keyword demand, store review rules).

## Rules

- Keyword demand or ranking is never stated: no figure without a measured source the user names.
- No fake reviews, ratings or "#1" claims; an unsourced one is removed, not reworded to sound safer.
- Competitor app names are not used as keywords.
- Limits come from `references/store-limits.json`, dated and unverified.

## Not for

- Build, signing, privacy manifest and screenshot pixel sizes for App Store submission → use `ios-submit-check`.
- Claims in other marketing text → use `claim-check`.
- Grammar and style → use `copyedit`.

## Level

- beginner: explain what each listing field is for and where it shows in the store.
- standard: as written.
- expert: failing fields and end state only. Every check still runs.

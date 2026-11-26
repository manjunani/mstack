---
name: ios-submit-check
description: Finds the mechanical reasons an iPhone app upload or App Store review would bounce: missing purpose strings for camera, location or photos, an incomplete privacy manifest, mismatched version and build numbers, a bad 1024 icon, wrong screenshot sizes. Use when the user is about to archive or upload to App Store Connect or TestFlight, or asks "is the app ready to submit", or wants a flagged privacy manifest entry, purpose string or version mismatch fixed so the check passes. Not for the store listing text (use store-listing-check) or for a full release checklist (use release).
license: MIT
metadata:
  pack: apps
  version: 0.3.1
  needs: python3
---

# iOS submit check

Produces a list of blockers and warnings, each with its file, found by reading the project without building it.

## Done when

- `scripts/submitcheck.py --project <dir>` exits 0, or every blocker it printed is in the reply with its file.
- The reply says the rule tables are unverified and names Apple's documentation as the source.

End in exactly one state: **pass** (no blocker in the fields read), **fail** (blockers listed), **not verified** (a part could not be read, or the user needs the tables checked against Apple first), or **blocked** (no project or Info.plist found).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| The app's folder | contains Info.plist files or an .xcodeproj with generated Info.plist keys | ask for the path; end as blocked |
| Store screenshots (optional) | a folder of PNG files | skip the screenshot check and say so |

## Steps

The script is `scripts/submitcheck.py` (`"${CLAUDE_SKILL_DIR}/scripts/submitcheck.py"` in Claude Code).

1. **Run.**
   ```
   python3 scripts/submitcheck.py --project <app folder> [--screenshots <folder>]
   ```
2. **Read each blocker.** Source matching is by text and over-reports. For each hit, open the file and confirm the API is really used.
3. **Fix what is true.** A purpose string says why the app needs the access, in the user's words. A privacy manifest reason is the reason the code really uses the API. Never choose a reason, or add a key, only to make the check pass; ask the user when the true answer is unclear.
4. **Run again** after changes.
5. **Report.** End state, then blockers with files, warnings, what the script does not check (review judgement, listing text, signing, App Store Connect's own checks), and that the tables in `references/store-rules.json` were written from memory and are unverified.

## Rules

- Do not upload, archive or change signing. This skill reads only.
- Do not present a table value as Apple's current rule. Apple's documentation is the source; the script prints that the tables are unverified.
- A pass here does not mean review will accept the app.

## Not for

- App Store listing text, keywords and description → use `store-listing-check`.
- The whole release (tag, build, upload, announce) → use `release`.
- VoiceOver and Dynamic Type → use `ios-a11y-check`.

## Level

- beginner: explain what a purpose string and a privacy manifest are for.
- standard: as written.
- expert: blockers and the RESULT line only. Every check still runs.

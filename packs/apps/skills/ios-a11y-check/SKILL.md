---
name: ios-a11y-check
description: Finds SwiftUI code that breaks VoiceOver and Dynamic Type, with file and line. Use when the user asks about VoiceOver labels, Dynamic Type, larger text or accessibility of an iPhone app. Flags icon buttons and images with no accessibility label, fixed font sizes, state shown by colour alone, and checks the largest-text screenshots exist and are not blank. Not for web pages (use a11y-audit) or for visual taste (use design-review).
license: MIT
metadata:
  pack: apps
  version: 0.1.0
  needs: python3; the simulator only for the screenshots
---

# iOS accessibility check

Produces a list of source lines to fix (with file and line) and a check of the largest-text screenshots, and names what only a VoiceOver pass can show.

## Done when

- `scripts/a11ycheck.py scan <source dir>` exits 0, or each failure is in the reply with file and line.
- `scripts/a11ycheck.py shots <folder> --expect <screens>` exits 0 for the screens the user named.
- The reply lists what was not verified (reading order, spoken sense of labels, clipped text, touch targets).

End in exactly one state: **pass**, **fail**, **not verified** (no largest-text screenshots, or no VoiceOver pass), or **blocked** (no Swift source).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| SwiftUI source | `.swift` files under the given folder | end as blocked |
| Largest-text screenshots | a folder of PNGs; to take them, `xcrun simctl ui <udid> content_size accessibility-extra-extra-extra-large` then a screenshot per screen (sim-proof or sim-flow) | the screenshot part is not verified |

## Steps

The script is `scripts/a11ycheck.py` (`"${CLAUDE_SKILL_DIR}/scripts/a11ycheck.py"` in Claude Code).

1. **Scan.** `python3 scripts/a11ycheck.py scan <app source folder>`. Text matching: open each hit and confirm it. A label set in a helper view elsewhere is not seen.
2. **Fix with the user's yes.** A label names the action ("Delete note"), not the icon ("trash"). Decorative images are marked decorative or hidden.
3. **Screenshots at the largest size.** Ask before changing the simulator's text size, and set it back afterwards. Then:
   ```
   python3 scripts/a11ycheck.py shots <folder> --expect home settings
   ```
   Look at each picture for clipped or overlapping text; the script cannot judge that.
4. **Report.** End state, failures with file and line, warnings, the screenshot result, and the not-verified list. Apple's accessibility documentation is the source for the APIs.

## Rules

- Never call a screen accessible from reading code alone.
- Do not hide an element from VoiceOver to silence a finding unless it really is decorative.
- Restore every simulator setting this skill changed.

## Not for

- Web pages and HTML → use `a11y-audit`.
- How the screen looks → use `design-review`.
- Store submission blockers → use `ios-submit-check`.

## Level

- beginner: explain VoiceOver, Dynamic Type and why fixed fonts fail.
- standard: as written.
- expert: findings and the RESULT lines. Both checks still run.

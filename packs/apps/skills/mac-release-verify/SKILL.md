---
name: mac-release-verify
description: Checks that a built Mac app or .dmg will open on other people's Macs: runs codesign strict verification, a Gatekeeper assessment with spctl and stapler validate for the notarisation ticket, and reports each as pass, fail or could not check. Use when a Mac build or disk image is ready to share, or the user asks "is it signed", "is it notarized", "will Gatekeeper block it" or "damaged and can't be opened". Not for iPhone builds (use ios-submit-check) or for checking a deployed web service (use deploy-check).
license: MIT
metadata:
  pack: apps
  version: 0.2.0
  needs: python3, macOS, codesign, spctl, xcrun stapler
---

# Mac release verify

Produces a three-line verdict (signature, Gatekeeper, stapled ticket) for one artifact, with the raw tool output kept under `.mstack/mac-release-verify/`.

## Done when

- `scripts/macverify.py <artifact>` exits 0, or each failing check is in the reply with the tool's own words.
- The reply says a first launch on a fresh Mac was not done by the script.

End in exactly one state: **pass**, **fail** (which check, with the output line), **not verified** (a check could not run, for example Gatekeeper switched off), or **blocked** (not macOS, no artifact).

## Needs

| Need | Check | If missing |
|---|---|---|
| macOS | `uname` says Darwin | end as blocked |
| codesign, spctl | `codesign --version`; `spctl --status` | they ship with macOS; if missing, end as blocked |
| stapler | `xcrun -f stapler` | comes with Xcode; the staple check is "could not check" |
| The artifact | a path to the .app or .dmg the users will get | ask for it; end as blocked |

## Steps

The script is `scripts/macverify.py` (`"${CLAUDE_SKILL_DIR}/scripts/macverify.py"` in Claude Code).

1. **Name the artifact** the users will really download, not a debug build.
2. **Run.**
   ```
   python3 scripts/macverify.py <App.app or App.dmg> [--mount] [--expect-version 1.4.0] [--expect-team ABCDE12345]
   ```
   For a .dmg, `--mount` attaches it read-only, checks the app inside, and detaches it.
3. **Read the detail lines**: signer, team, ad hoc or not, hardened runtime flag. An ad hoc signature passes `codesign` on this Mac but Gatekeeper rejects it elsewhere.
4. **Report.** End state, then each check with its line, the raw output folder, and what remains for a person: open a downloaded copy on a Mac that has never run this app.

## Rules

- Read-only. Do not sign, notarise, staple, upload or install. Those use the user's Apple account and are the project's own scripts.
- Never ask for or print signing passwords, keys or app-specific passwords.
- "accepted" from Gatekeeper on this Mac can come from an online ticket; the staple check is what proves an offline first launch.
- Apple's notarisation documentation is the source for what each tool's output means.

## Not for

- iPhone App Store readiness → use `ios-submit-check`.
- Tauri configuration before the build → use `tauri-preflight`.
- A deployed web service → use `deploy-check`.

## Level

- beginner: explain signing, Gatekeeper and the stapled ticket in one line each.
- standard: as written.
- expert: the three check lines and the RESULT line. All three checks run at every level.

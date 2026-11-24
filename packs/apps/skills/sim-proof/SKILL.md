---
name: sim-proof
description: Proves an iPhone app launches on the simulator and shows a real screen: installs the built .app on a booted simulator, launches it, checks the process stays alive and takes a screenshot that a pixel check confirms is not blank. Use when a SwiftUI change needs simulator evidence, or the user asks "does it run", "show me it on the iPhone simulator" or "screenshot the app". Not for driving a multi-step flow with taps (use sim-flow) or for judging how the screen looks (use design-review).
license: MIT
metadata:
  pack: apps
  version: 0.2.1
  needs: python3, Xcode command-line tools (xcrun simctl), a booted simulator, a simulator build of the app
---

# Sim proof

Produces one screenshot and one record file that show the app installed, launched, stayed alive and drew a real picture.

## Done when

- `scripts/simproof.py run` exits 0 and its record under `.mstack/sim-proof/` says `pass`.
- The screenshot path is in the reply, and someone (you or the user) opened it and named the screen it shows.

End in exactly one state: **pass**, **fail** (which step, with its output), **not verified** (the picture could not be judged, or nobody looked at which screen it is), or **blocked** (no Xcode tools, no booted simulator, no simulator build).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| Xcode command-line tools | `xcrun simctl help` | say they come with Xcode; installing is the user's call; end as blocked |
| A booted simulator | `python3 scripts/simproof.py devices` | show the list; boot one only if the user agrees (`xcrun simctl boot <udid>`); else blocked |
| A simulator build (.app) | the project's own build command | ask for it or run the project's build; a device build will not install |

## Steps

The script is `scripts/simproof.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/simproof.py"`.

1. **Check needs.** `python3 scripts/simproof.py devices`. Exit 2 means blocked; report what it printed.
2. **Build** with the project's own command for a simulator destination. A failed build is a **fail**; show the first error line. The script prints the binary's age: if the source changed after it, build again.
3. **Run.**
   ```
   python3 scripts/simproof.py run --app <path/to/App.app> --screen "<screen the user named>"
   ```
   Add `--udid` when more than one simulator is booted, `--settle 8` for a slow first screen.
4. **Look at the screenshot.** The script proves a live process and a non-blank picture, not which screen. Open the PNG and say what it shows. If the named screen is not the first one, this skill cannot reach it: use `sim-flow`.
5. **On a fail** after launch (process ended), read the newest crash report with `crash-read` if installed; otherwise give the user the path `~/Library/Logs/DiagnosticReports/`.
6. **Report.** End state first, then the screenshot path, the record path, the device, and what was not verified.

`check <image.png>` judges any screenshot file on its own.

## Rules

- Do not boot, erase or shut down a simulator without the user's yes. Leave the machine as found.
- A launch command that returned 0 proves nothing alone; the process check and the picture check decide.
- The blank thresholds in `references/image-check.json` are mstack defaults, not Apple facts; the script prints that.
- Simulator behaviour is Apple's to define; Apple's Xcode documentation is the source, not this skill.

## Not for

- Tapping through several screens → use `sim-flow`.
- Judging layout, spacing or taste → use `design-review`.
- Signed Mac builds → use `mac-release-verify`.

## Level

- beginner: explain what a booted simulator is and why a blank picture fails.
- standard: as written.
- expert: report the RESULT line and the screenshot path only. Every check still runs.

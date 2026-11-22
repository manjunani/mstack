---
name: webxr-verify
description: Proves a WebXR page works without a headset: checks the code for an XR session, render loop, input and exit, and judges an emulated session by head-pose screenshots and console errors. Use when a WebXR, VR or AR web page that enters an XR session was built or changed, its Enter VR button or hands and controllers fail, or the user asks if it works on Quest. Not for three.js pages with no XR session (use three-verify in the 3d pack), VR UI comfort or text size (use xr-comfort-review) or which platform a repo targets (use xr-target).
license: MIT
metadata:
  pack: xr
  version: 0.1.0
  needs: python3, a browser the agent can drive, a WebXR emulator
---

# WebXR verify

Produces a static scan result, an emulated-session verdict, and a list of what still needs a real headset.

## Done when

- `xr_scan.py` passed: a session request for the right mode and a render loop that runs in XR exist; warnings are listed.
- An emulated session started, and every required head pose and input mode has a capture that passed the pixel check.
- The console is clean and draw calls are inside the limit.
- The reply lists what the emulator cannot prove: real frame rate, comfort, tracking.

End in exactly one state: **pass**, **fail** (quote the failing line), **not verified** (say which check could not run), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| a browser the agent can drive, with screenshots | the browser tool of this session | the scan still runs; the session check is not verified |
| a WebXR emulator in that browser | `navigator.xr` exists in the page after loading it | end as blocked for the session part; ask the user which emulator to use |

## Steps

Scripts are in this skill's `scripts/` folder (`"${CLAUDE_SKILL_DIR}/scripts/"` in Claude Code).

1. **Scan.**
   ```
   python3 scripts/xr_scan.py <project> --mode vr
   ```
   A fail here (no session request, no XR render loop) is fixed before any browser work.
2. **Serve over https or localhost.** WebXR needs a secure context.
3. **Emulate.** Open the page with the emulator loaded. Load `scripts/session_snippet.js` (its header shows the calls). Enter the session, then capture each head pose (front, left, right at least) and each input mode (controllers, hands). How to move the head or switch input depends on the emulator: read its own docs, do not guess. Screenshot after each capture and add the file name. Save `report()` as `report.json`. Format: `references/session-report.md`.
4. **Check.**
   ```
   python3 scripts/check_session.py report.json --mode immersive-vr --poses front,left,right --inputs controllers,hands
   ```
5. **Look** at each screenshot and say what it shows.
6. **Device rung (only if a headset is attached).** For Meta Quest, use Meta's own device tools or skills if installed for the on-device screenshot and logs. If not, say the device check was not done.
7. **Report.** End state first, then scan rows, session verdict, captures, and the list of what an emulator cannot prove.

## Rules

- An emulator's frame time is never reported as headset performance.
- A missing capture is a fail, not a skip. A skipped device check is "not verified".
- Do not change the page to satisfy the scan's warnings without asking; they are often design choices.

## Not for

- A three.js page with no XR session → use `three-verify`.
- Distances, text sizes and head-locked UI → use `xr-comfort-review`.
- Which platform the repo targets → use `xr-target`.

## Level

- beginner: explain secure context, the two rungs (emulator, device) and why frame rate needs a headset.
- standard: as written.
- expert: scan and session verdicts only. Every check still runs.

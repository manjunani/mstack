---
name: xr-comfort-review
description: Measures every UI element of a running VR or AR scene: distance from the head, visual angle of text, angle off the forward view, target size and head-locked placement, each with pass or fail against dated limits. Use when the user asks if a VR menu is readable, too close, too small or uncomfortable, or before shipping XR UI. Not for checking a WebXR session starts or renders (use webxr-verify).
license: MIT
metadata:
  pack: xr
  version: 0.2.0
  needs: python3, a browser running the scene (three.js)
---

# XR comfort review

Produces a measured row per UI element and per check, taken from the running scene, never from reading the code.

## Done when

- A scene dump was made by `scripts/scene_dump.js` in the running page, with the head where the user's head would be.
- `comfort.py` ran on it; every element has measured rows, and every skipped check says why.
- The reply says the limits are unverified working values and lists what was not measured (locomotion, frame rate, feel).

End in exactly one state: **pass**, **fail** (quote the failing line), **not verified** (say which check could not run), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| the scene running in a browser the agent can drive | the browser tool of this session | end as blocked; a dump typed by hand is not accepted |
| three.js | `THREE` reachable in the page | other engines: write the same JSON from that engine, or end as not verified |

## Steps

Scripts are in this skill's `scripts/` folder (`"${CLAUDE_SKILL_DIR}/scripts/"` in Claude Code).

1. **Mark the UI.** In the app's code, set `userData.mstackUi = { name, textHeight, interactive }` on each panel, label and button. `textHeight` is the height of one line of text in metres.
2. **Place the head.** Put the camera (or XR camera) at standing eye height where the user starts.
3. **Dump.** Run `scripts/scene_dump.js` in the page and save the JSON. One dump per screen or state that matters.
4. **Measure.**
   ```
   python3 scripts/comfort.py scene_dump.json
   ```
5. **Report.** End state first, then failing rows with the element name and the number, then skipped checks, then what was not measured.

## Rules

- Compute, never estimate. No angle or distance is worked out in prose.
- A check with a missing value is skipped and named; it never counts as ok.
- Limits live in `references/comfort_thresholds.json`. They are round working values, not taken from any vendor list; re-source each from a primary document before a fail blocks a release.
- Comfort of motion (speed, turning, acceleration) is not measured here; say so.

## Not for

- Whether the session starts and renders → use `webxr-verify`.
- Visual design and taste of the UI → use `design-review`.

## Level

- beginner: explain visual angle and why head-locked UI tires the eyes.
- standard: as written.
- expert: failing rows and the end state only. Every check still runs.

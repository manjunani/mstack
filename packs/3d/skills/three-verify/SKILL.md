---
name: three-verify
description: Proves a three.js or React Three Fiber scene renders and reports fps or frame time, draw calls, triangles and a memory leak test when scenes are switched. Use when the canvas is black, after bumping three to a new version, or asked "does the scene work", "how many fps", "how heavy is it" or whether old APIs like outputEncoding still work. Checks code against the installed three version and screenshots per camera pose. Not for one model file (use gltf-gate) or a WebXR session (use webxr-verify).
license: MIT
metadata:
  pack: 3d
  version: 0.2.2
  needs: python3, a browser with a screenshot tool; node optional
---

# three-verify

Produces two script results: a version preflight of the code and a verdict on a capture report taken from the running page.

## Done when

- `preflight.py` ran on the project and every flagged line is fixed or listed.
- A capture report exists with at least two camera poses, and `check_capture.py` passed on it.
- Every screenshot holds a picture (decoded from the file), the console is clean, counters are inside the profile, and geometries and textures return to their start count after dispose.
- A frame time is stated only if it was measured on a hardware GPU adapter; otherwise the reply says "not measured".

End in exactly one state: **pass**, **fail** (quote the failing line), **not verified** (say which check could not run), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| three.js installed in the project | `node_modules/three/package.json` exists | preflight ends as not verified; ask the user to install dependencies |
| a browser the agent can drive, with screenshots | the browser tool of this session | the capture cannot be made: end as not verified |

## Steps

Scripts are in this skill's `scripts/` folder (`"${CLAUDE_SKILL_DIR}/scripts/"` in Claude Code).

1. **Preflight.**
   ```
   python3 scripts/preflight.py <project>
   ```
   A confirmed line is code that does not match the installed version. Fix the code, not the version, unless the user asks. The change list in `references/api_changes.json` is short and unverified.
2. **Start the page** with the project's own dev command. Note the URL.
3. **Capture.** Load `scripts/capture_snippet.js` into the page (its header shows how). Call `mark('before')` before loading if you can, then one `pose()` per named camera position, `mark('loaded')`, dispose the scene, `mark('after_dispose')`. If anything stays after dispose, load and dispose once more and `mark('after_dispose_2')`: three.js keeps some objects of its own, and only growth per load is a leak. After each pose, take a browser screenshot and add its file name to that pose. Save `report()` as `report.json` next to the screenshots. Format: `references/capture-report.md`.
4. **Check.**
   ```
   python3 scripts/check_capture.py report.json --profile desktop-web
   ```
   Add `--claims-frame-time` if the reply will state speed, and `--refresh-hz 72` (or the target rate) to judge it.
5. **Look** at each screenshot and say what it shows.
6. **Report.** End state first, then poses, console, counters against the profile, leak result, GPU adapter, and what was not verified.

`scripts/pngstats.py stats <png>` checks one screenshot on its own.

## Rules

- A screenshot that saved is not a render. Only the pixel check counts.
- Headless browsers often use a software renderer. Read the adapter name before any word about speed. A frame time no lower than the idle page's (`frameTime(120, 'idle')`) is the browser's frame schedule, not the scene.
- Programs left after dispose are a warning (they are often cached); geometries and textures left are a leak.
- Never edit numbers in the capture report.

## Not for

- Checking one model file's structure and budget → use `gltf-gate`.
- A WebXR session with a headset emulator → use `webxr-verify`.
- How the page looks as a design → use `design-review`.

## Level

- beginner: explain draw calls, the software renderer trap and what a leak is.
- standard: as written.
- expert: show the script output and the end state only. Every check still runs.

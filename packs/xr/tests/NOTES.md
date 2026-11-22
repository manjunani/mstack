# mstack-xr: what was tested and what was not

Date: 2026-11-22. Machine: macOS, Python 3.14, Node 26, Apple `usdzip`, `usdcat` and `usdchecker` present. Not installed: any WebXR emulator, Playwright, a GLB to USDZ converter. No headset attached. No browser was driven.

## How to repeat

```
python3 packs/xr/tests/scripts/run_cases.py .testrun/<new folder>
```

The test borrows the 3d pack's `fixtures.py` to build models and images (only the test does; the skills carry their own copies of `glb.py` and `pngstats.py`, and the test checks the copies are identical). Last run: **57 checks, 0 failed**.

## Per skill

### webxr-verify
- Tested: `xr_scan.py` on throwaway projects: complete VR page passes with evidence lines and https seen; the same page asked for AR fails; window.requestAnimationFrame only fails; no input, exit or https gives warnings and a pass; A-Frame page passes; no XR fails; empty folder blocked. `check_session.py`: good report passes and prints the emulator limits; session not started, wrong mode, one black pose, hands never captured, console error, draw calls over the limit all fail; missing adapter is not verified; an emulator frame time is refused; unreadable report. `session_snippet.js` pixel statistics under Node.
- Not run: a real emulated session. No emulator was installed, so how to set head poses and switch input is left to the emulator's own docs; the snippet's `enter`, `capture` and `exit` were never run in a browser. Untested assumption: reading pixels from the canvas during an emulated session works. If it does not, the screenshot files still decide (the checker prefers them).
- Device rung: not run (no headset).

### xr-comfort-review
- Tested: panel at 1.5 m passes; 0.3 m fails; tiny text at 3 m fails (0.19 deg); 60 deg off forward fails; head-locked element 30 deg off fails while world-locked is allowed 40; small button at 2 m fails (0.86 deg); missing size and text height are skipped and end as not verified; no elements; no head. `scene_dump.js` under Node with a mock scene (head-locked flag, scaled text height, sizes) and its dump through `comfort.py`.
- Not run: the dump in a real three.js scene or XR camera. Thresholds are round working values chosen for mstack, not copied from any vendor list, all unverified; they need re-sourcing from primary documents.

### xr-target
- Tested: three.js WebXR repo with version; Unity Quest repo (Meta SDK, OpenXR, Quest manifest) with the handoff to Meta's skills; visionOS Swift; mixed A-Frame and Godot repo lists both and asks; no signal is not verified; not a folder is blocked.
- Not run: real repositories. Signal patterns are written from memory and are not complete (Babylon, Unreal and ARCore patterns had no test case).

### webar-preview
- Tested: GLB size against declared size (pass, 100 times too big names centimetres, longest side, no size blocked, error page fails, floating base pointed out); USDZ twins built with the real `usdzip` and checked with the real `usdcat --flatten` and `usdchecker --arkit`: matching twin passes, centimetre layer fails at 0.01 times the GLB, compressed archive fails, non-USDZ fails, missing file; convert without a converter is blocked; page written with model-viewer element, `ios-src`, `ar-scale="fixed"` and a Quick Look link, model files copied; existing folder blocked; wrong size writes no page; no AR entry point blocked.
- Not run: a real conversion (no converter installed); opening the page on a phone; the model-viewer attributes are from memory. USD bounds come from `extent` values and translate, scale and matrix ops only; rotations are flagged as not evaluated. A binary (usdc) layer without `usdcat` cannot be measured.

## Faults the tests caught

1. My own expectation for the scene-dump case was wrong (1 cm text scaled by 2 at 1 m is 1.15 deg, a pass). The script was right; the test was fixed.

## Names

Skill names follow `docs/SKILLS.md`. No rename proposed.

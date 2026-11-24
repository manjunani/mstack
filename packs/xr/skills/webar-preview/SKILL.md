---
name: webar-preview
description: Turns a .glb into a phone AR preview at true size: compares the model's bounding box in metres with the real object's declared size, checks a .usdz twin with Apple's usdcat and usdchecker, and writes a small page with an AR viewer element. Use when the user wants to see a product or model in their room on a phone, or asks for Quick Look or Scene Viewer. Not for headset WebXR pages (use webxr-verify).
license: MIT
metadata:
  pack: xr
  version: 0.2.1
  needs: python3; optional usdcat, usdchecker, a GLB to USDZ converter, a model-viewer build
---

# WebAR preview

Produces a size check against the real object, a checked USDZ twin when there is one, and a page folder with the viewer and the model files.

## Done when

- The real size was declared by the user (never assumed), and `ar_preview.py scale` passed.
- The USDZ, if any, passed `ar_preview.py usdz` against the GLB and the declared size.
- `ar_preview.py page` wrote the page and every file it refers to exists.
- The reply says that viewing it on a real phone is still a step for a person.

End in exactly one state: **pass**, **fail** (quote the failing line), **not verified** (say which check could not run), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| usdcat and usdchecker (Apple, or OpenUSD) | `usdcat --help` | the USDZ size or AR check is not verified |
| a GLB to USDZ converter | `python3 scripts/ar_preview.py convert` says which it found | end the conversion as blocked; say what to get; install nothing |
| a model-viewer build for the page | a local file or an https address the user gives | page offers only the Quick Look link, or blocked if there is no USDZ either |

## Steps

The script is `scripts/ar_preview.py` in this skill's folder (`"${CLAUDE_SKILL_DIR}/scripts/ar_preview.py"` in Claude Code).

1. **Ask for the real size** of the object in metres: width x height x depth, or just height, or the longest side.
2. **Check scale.**
   ```
   python3 scripts/ar_preview.py scale model.glb --size 0.45x0.9x0.45
   ```
   A ratio of 100 or 1000 points to centimetres or millimetres. Fix the model's scale in its source, not in the page.
3. **USDZ.** If the user has one, or a converter is installed:
   ```
   python3 scripts/ar_preview.py convert model.glb --out model.usdz
   python3 scripts/ar_preview.py usdz model.usdz --glb model.glb --size 0.45x0.9x0.45
   ```
4. **Page.**
   ```
   python3 scripts/ar_preview.py page --glb model.glb --usdz model.usdz --viewer-script <file or https address> --out preview/ --size 0.45x0.9x0.45
   ```
5. **Serve over https** for the phone; AR viewers refuse plain http from another device.
6. **Report.** End state first, then measured against declared size, USDZ result, the page path, and "needs a phone".

## Rules

- The size is never assumed or derived from the model itself; a check against the model's own numbers proves nothing.
- The model's base sits at y = 0, or it will float or sink on the surface; the scale step says so.
- The viewer attributes on the page are written from memory; check them against the viewer version used.

## Not for

- A WebXR page for a headset → use `webxr-verify`.
- The model's structure and budget → use `gltf-gate` (3d pack), if installed.

## Level

- beginner: explain Quick Look, Scene Viewer and why size goes wrong.
- standard: as written.
- expert: the size table and the page path only. Every check still runs.

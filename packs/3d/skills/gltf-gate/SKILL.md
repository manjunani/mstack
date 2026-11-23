---
name: gltf-gate
description: Stops a .glb or .gltf model from shipping until it is a real file, sound in structure, inside a budget and looked at. Reports triangles, materials, textures and size in metres, then writes a manifest. Use when a model was exported, downloaded, generated or optimised, or the user asks "is this model ok", "will it run on Quest" or "why is it so big". Not for checking a whole three.js page (use three-verify).
license: MIT
metadata:
  pack: 3d
  version: 0.2.0
  needs: python3; optional gltf_validator, gltf-transform, a browser for renders
---

# glTF gate

Produces a gate manifest under `.mstack/gltf-gate/` that says pass, fail or not verified for one exact file (by hash).

## Done when

- `gate.py check` ran on the file with a named budget profile and its last line is read.
- Structure errors are zero, every budget line is ok or waived in writing, and the validator reported zero errors.
- At least four turntable screenshots passed the pixel check, and the reply says in words what they show.
- The manifest exists. Anything that did not run is listed as not verified.

End in exactly one state: **pass**, **fail** (quote the failing line), **not verified** (say which check could not run), or **blocked** (say what is needed from the user).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| Khronos glTF validator | `gltf_validator --version` | carry on; the result can be at best not verified |
| glTF Transform CLI (only for optimising) | `gltf-transform --version` | `optimise` ends as blocked; say how to get it, install nothing |
| a browser that can screenshot a page | the browser tool of this session | the render check stays not verified |

## Steps

Scripts are in this skill's `scripts/` folder (`"${CLAUDE_SKILL_DIR}/scripts/"` in Claude Code).

1. **Check needs.** Run the checks above and say which are missing.
2. **Pick the profile** with the user: `python3 scripts/gate.py profiles`. Every number in it is an unverified working value; say so once.
3. **Inspect.** `python3 scripts/gate.py inspect <file>`. A web page, an API reply, a zip or an empty download saved as `.glb` fails here.
4. **Render.** In a browser, load the model in a plain three.js page and take four screenshots or more from fixed angles around it (front, sides, back, top). Save them as PNG.
5. **Check.**
   ```
   python3 scripts/gate.py check <file> --profile <name> --renders front.png left.png back.png right.png
   ```
   A budget line that is over can be accepted only by the user, with a reason: `--waive triangles="hero asset, owner agreed"`.
6. **Look.** Open each screenshot. Say what it shows: the object, its facing, missing textures, holes. Pixels prove a picture exists, not that it is the right one.
7. **Optimise (only if asked).**
   ```
   python3 scripts/gate.py optimise <file> --out <new file> --tool-args "<flags from gltf-transform optimize --help>"
   python3 scripts/gate.py compare --before a1.png a2.png --after b1.png b2.png
   ```
   Then run `check` on the new file. The input is never changed.
8. **Report.** End state first, then the budget table, validator counts, what the renders show, the manifest path, and what was not verified.

`scripts/glb.py` is the reader the other scripts share; `scripts/pngstats.py` decodes the screenshots.

## Rules

- A missing tool never becomes a pass. Without the validator or renders the best result is not verified.
- Budget numbers are working values until someone re-sources them. Do not present them as platform limits.
- Never write over the input or an existing output file.
- Size is reported in metres along +Y up. A model 100 times too big was usually made in centimetres; say so.

## Not for

- Checking a three.js page renders and what it costs → use `three-verify`.
- Checking bones and animation → use `rig-motion-check`.
- Proving a claim about the whole project → use `verify`.

## Level

- beginner: explain each budget line and why texture size matters more than triangle count on a headset.
- standard: as written.
- expert: show the budget table and the manifest path only. Every check still runs.

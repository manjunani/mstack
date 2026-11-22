# mstack-3d: what was tested and what was not

Date: 2026-11-22. Machine: macOS, Python 3.14, Node 26. Not installed: Blender, glTF Transform, the Khronos glTF validator, ImageMagick, OpenSCAD, Playwright. No browser was driven.

## How to repeat

```
python3 packs/3d/tests/scripts/run_cases.py .testrun/<new folder>
```

`fixtures.py` builds every test file from code (tiny GLB and glTF models, broken ones, a rigged model with seven clips, PNGs in five colour types). Each case prints its exit code and the expected one. Last run: **162 checks, 0 failed**.

Stand-ins: where a tool is missing, the test writes a small fake program with that name (`gltf_validator`, `gltf-transform`, `blender`) into the test folder. Those cases prove how the wrapper reads the tool's output and handles its failures. They do NOT prove the real tool behaves that way.

## Per skill

### gltf-gate
- Tested: GLB and glTF parsing (header, chunks, BIN, external buffer); structural errors (wrong header length, chunk longer than file, cut-off file, accessor outside its buffer view, missing asset field, dangling mesh and material indices, POSITION without min and max, JSON that does not parse, missing external buffer); non-model files saved as .glb (HTML error page, API JSON reply, empty, zip); triangle, draw-call and texture counts, PNG texture size, bounding box in metres through node transforms, a mesh used twice; budget pass, over-budget fail, written waiver, waiver without reason; the check without validator or renders ends as not verified and writes a manifest; render pixel check (blank, too few views, 16-bit image unreadable, same image four times); optimise wrapper (missing tool blocked, output exists, no output, size drift, input changed); before and after image compare; the input file is unchanged after every run.
- Not run: the real Khronos validator (not installed; report format taken from memory, so the parser may need a fix on first real run), the real gltf-transform (flags are passed through, not assumed), real turntable renders in a browser. JPEG, WebP and KTX2 size readers were not exercised. Sparse accessors and Draco or meshopt compressed files are not decoded (reported as unknown, not tested).
- Budgets in `references/budgets.json` are unverified working values.

### three-verify
- Tested: `pngstats.py` decodes RGBA, RGB, palette and grey+alpha PNG through all five row filters, pixel for pixel; flags black, flat grey, transparent and single-colour images; refuses 16-bit and interlaced PNG and non-PNG files. `preflight.py` on fake projects with a stand-in `node_modules/three`: no three, declared but not installed, clean code on r160, removed colour API confirmed by the build text, missing addon file, examples/js on r160, new API on r140, addons alias on r140, deprecated name still in the build. `check_capture.py`: good report, black screenshot, flat page numbers, file wins over page numbers, console errors, counters over budget, texture leak, software renderer with frame time, missing adapter, frame time over a refresh budget, missing poses, missing dispose, unreadable report. `capture_snippet.js` ran under Node with a mock WebGL context and mock renderer; its report passed the checker.
- Not run: the snippet in a real browser with real three.js; real screenshots; the software-renderer list against real adapter strings. The API change list is from memory and unverified.

### rig-motion-check
- Tested: bone and clip listing; forward kinematics checked against hand-computed positions (90 and 45 degree hip rotation); planted foot passes; 0.6 m slide fails; in-place clip; 0.1 m sink fails; a real step (lift, travel, land) passes; animated scale fails; cubic spline clip; all clips at once; wrong floor too high (fail) and too low (not verified); clip that does not move the bone; unknown, ambiguous bone; unknown clip; model without animation; broken and non-model files; the table file is not overwritten.
- Not run: any real exported character (Mixamo, Blender, generator output). No skinned mesh deformation is computed; the script says so in every run. Quaternion slerp and spline maths were checked only through the cases above. Thresholds are unverified.

### blender-task
- Tested: detection on this machine (absent, ends blocked), explicit wrong path, a program that answers like something else; run with a stand-in Blender: state file written, never overwritten, exit 0 without state fails, job error fails, a changed .blend fails, missing job blocked. Fact checker on hand-written state files: all facts hold, wrong size, scale not applied, modifier left, polygon limit after modifiers, object that should be gone, missing object, wanted modifier, centimetre unit scale, missing values (not verified), empty facts (not verified, never pass), unreadable state.
- Not run: real Blender. `assets/state_dump.py` was only compiled, never run inside Blender; its `bpy` calls are written from memory and may need fixes on first real use. Renders from Blender are not part of the script.

### text-to-3d
- Tested: approve refuses without `--user-approved` and records nothing; empty cost refused; approval recorded; accept without approval blocked; HTML error page rejected without using up the approval; missing file blocked; real model without a gate manifest is not verified; after a gate pass (stand-in validator, real pictures) the same file is accepted; a second file on one approval is blocked; over budget and structural errors rejected; the ledger lists cost and outcome.
- Fault caught by the tests: two approvals made in the same second got the same id and the second crashed; fixed with a random part in the id.
- Not run: any provider. The skill ships no provider details by design.

## Faults the tests caught (all fixed)

1. PNG fixture encoder ignored bit depth (test-side bug).
2. `gate.py optimise` took extra tool flags as a positional remainder, which swallowed `--out`; changed to `--tool-args "<string>"`.
3. Capture snippet gave no pixel hash, so the checker could not warn about poses with identical images; added.
4. text-to-3d approval id collided within one second (see above).

## Names

Skill names follow `docs/SKILLS.md`. No rename proposed.

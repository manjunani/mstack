"""Script tests for the mstack-3d pack. Builds every fixture from code, runs each script and compares exit codes.

Usage: run_cases.py <new folder under .testrun/>      (the folder must not exist yet)

Each case line shows the exit code and the expected one. Stand-ins: where a case needs a tool that is not
installed (Blender, the Khronos validator, gltf-transform), the test writes a small fake program with that
name into <folder>/bin. Those cases prove the wrapper's handling of the tool's output, NOT the real tool.
"""
import argparse
import hashlib
import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
PACK = HERE.parent.parent
sys.path.insert(0, str(HERE))
import fixtures  # noqa: E402

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("folder", type=pathlib.Path)
args = parser.parse_args()
if args.folder.exists():
    sys.exit(f"refusing: {args.folder} already exists")
ROOT = args.folder.resolve()
M = fixtures.write_models(ROOT / "models")
I = fixtures.write_images(ROOT / "images")
BIN = ROOT / "bin"
BIN.mkdir()
results = []


def skill(name, script):
    return str(PACK / "skills" / name / "scripts" / script)


def case(name, command, expect, contains=(), env=None, cwd=None):
    merged = {**os.environ, **(env or {})}
    out = subprocess.run([sys.executable, *map(str, command)], capture_output=True, text=True, env=merged, cwd=cwd or ROOT)
    text = out.stdout + out.stderr
    missing = [c for c in contains if c not in text]
    ok = out.returncode == expect and not missing
    results.append(ok)
    print(f"{'ok  ' if ok else 'FAIL'} {name}: exit {out.returncode} (expect {expect})" + (f" missing text {missing}" if missing else ""))
    if not ok:
        print("     | " + "\n     | ".join(text.strip().splitlines()[-6:]))
    return text


def expect(name, condition, detail=""):
    results.append(bool(condition))
    print(f"{'ok  ' if condition else 'FAIL'} {name}" + (f": {detail}" if detail and not condition else ""))


def fake(name, body):
    path = BIN / name
    path.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def with_bin():
    return {"PATH": str(BIN) + os.pathsep + os.environ.get("PATH", "")}


def sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


GATE, GLB, PNG = skill("gltf-gate", "gate.py"), skill("gltf-gate", "glb.py"), skill("three-verify", "pngstats.py")
cube_before = sha(M["cube.glb"])

print("#### shared readers are identical copies")
for other in ("rig-motion-check", "text-to-3d"):
    expect(f"glb.py in {other} equals the gltf-gate copy", sha(skill(other, "glb.py")) == sha(GLB))
expect("pngstats.py in gltf-gate equals the three-verify copy", sha(skill("gltf-gate", "pngstats.py")) == sha(PNG))

print("#### gltf-gate: inspect")
case("valid cube", [GATE, "inspect", M["cube.glb"]], 0, ["12 drawn", "1.0000 x 2.0000 x 3.0000 m", "png 8x4"])
case("one mesh used twice counts twice", [GATE, "inspect", M["two_boxes.glb"]], 0, ["24 drawn in the default scene (12 stored)", "6.0000 x 2.5000 x 3.0000"])
case("gltf with external buffer", [GATE, "inspect", M["cube_external.gltf"]], 0, ["12 drawn"])
case("header length wrong", [GATE, "inspect", M["bad_length.glb"]], 1, ["header says the file is 999999 bytes"])
case("chunk longer than file", [GATE, "inspect", M["bad_chunk.glb"]], 1, ["claims 5000000 bytes"])
case("file cut short", [GATE, "inspect", M["truncated.glb"]], 1, ["only 328 remain"])
case("accessor outside buffer", [GATE, "inspect", M["bad_accessor.glb"]], 1, ["accessor 1: needs 7200 bytes, bufferView 1 holds 72"])
case("asset field missing", [GATE, "inspect", M["no_asset.glb"]], 1, ["asset.version is missing"])
case("dangling mesh and material", [GATE, "inspect", M["bad_refs.glb"]], 1, ["mesh 7 does not exist", "material 4 does not exist"])
case("POSITION without min and max", [GATE, "inspect", M["no_minmax.glb"]], 1, ["has no min and max"])
case("JSON chunk is not JSON", [GATE, "inspect", M["not_json.glb"]], 1, ["JSON chunk does not parse"])
case("web error page named .glb", [GATE, "inspect", M["error_page.glb"]], 1, ["web page or error page"])
case("API reply named .glb", [GATE, "inspect", M["api_reply.glb"]], 1, ["API reply"])
case("empty file", [GATE, "inspect", M["empty.glb"]], 1, ["0 bytes"])
case("zip named .glb", [GATE, "inspect", M["archive.glb"]], 1, ["zip archive"])
case("gltf whose buffer file is gone", [GATE, "inspect", M["cube_lost_buffer.gltf"]], 1, ["gone.bin"])
case("no such file", [GATE, "inspect", ROOT / "nope.glb"], 2, ["no such file"])
case("glb.py on its own", [GLB, M["cube.glb"], "--json"], 0, ['"triangles_in_scene": 12'])

print("#### gltf-gate: check (no validator installed, no renders)")
proj = ROOT / "proj"
proj.mkdir()
tight = ROOT / "tight_budgets.json"
budgets = json.loads((PACK / "skills" / "gltf-gate" / "references" / "budgets.json").read_text())
budgets["profiles"]["tiny"] = {"triangles": {"value": 10, "unit": "triangles", "source": "test", "checked": "2026-11-22", "verified": False}}
tight.write_text(json.dumps(budgets))
real_validator = shutil.which("gltf_validator")
case("profiles list says unverified", [GATE, "profiles"], 0, ["quest-webxr", "UNVERIFIED"])
if real_validator:
    print("note: a real gltf_validator is on PATH; the two 'not installed' cases are skipped")
else:
    case("sound model, tools missing -> not verified", [GATE, "check", M["cube.glb"], "--profile", "quest-webxr", "--project", proj], 2,
         ["Khronos validator not run", "render check", "manifest:"])
    expect("manifest written with result 'not verified'",
           any(json.loads(p.read_text())["result"] == "not verified" for p in (proj / ".mstack" / "gltf-gate").glob("cube-*.json")))
case("over budget -> fail", [GATE, "--budgets", tight, "check", M["cube.glb"], "--profile", "tiny", "--project", proj], 1, ["triangles 12 is over the tiny budget of 10"])
case("waiver without a reason -> blocked", [GATE, "--budgets", tight, "check", M["cube.glb"], "--profile", "tiny", "--waive", "triangles=ok", "--project", proj], 2, ["blocked"])
case("unknown profile -> blocked", [GATE, "check", M["cube.glb"], "--profile", "nope", "--project", proj], 2, ["blocked: no budget profile"])
case("error page -> fail", [GATE, "check", M["error_page.glb"], "--profile", "quest-webxr", "--project", proj], 1, ["RESULT fail"])
case("structural error -> fail", [GATE, "check", M["bad_accessor.glb"], "--profile", "quest-webxr", "--project", proj], 1, ["structural errors"])

print("#### gltf-gate: check with a STAND-IN validator and render files")
fake("gltf_validator", """import json, os, sys
mode = os.environ.get("FAKE_VALIDATOR", "clean")
if mode == "garbage":
    print("validator exploded")
    sys.exit(0)
errors = 2 if mode == "errors" else 0
print(json.dumps({"validatorVersion": "stand-in", "issues": {"numErrors": errors, "numWarnings": 1, "messages": [
    {"code": "STAND_IN", "message": "message from the stand-in", "severity": 0 if errors else 1, "pointer": "/meshes/0"}]}}))
""")
four = [I["picture.png"], I["picture_rgb.png"], I["picture_shifted.png"], I["palette.png"]]
env = with_bin()
case("validator clean + 4 real pictures -> pass", [GATE, "check", M["cube.glb"], "--profile", "quest-webxr", "--project", proj, "--renders", *four], 0,
     ["0 errors, 1 warnings", "4 views hold a picture", "RESULT pass"], env=env)
case("waived overrun is kept in writing", [GATE, "--budgets", tight, "check", M["cube.glb"], "--profile", "tiny", "--project", ROOT / "proj2",
                                          "--waive", "triangles=hero asset, owner accepted it", "--renders", *four], 0, ["WAIVED", "hero asset"], env=env)
case("validator errors -> fail", [GATE, "check", M["cube.glb"], "--profile", "quest-webxr", "--project", ROOT / "proj3", "--renders", *four], 1,
     ["validator reports 2 errors"], env={**env, "FAKE_VALIDATOR": "errors"})
case("validator output unreadable -> not verified", [GATE, "check", M["cube.glb"], "--profile", "quest-webxr", "--project", ROOT / "proj3", "--renders", *four], 2,
     ["gave no readable report"], env={**env, "FAKE_VALIDATOR": "garbage"})
case("a black render -> fail", [GATE, "check", M["cube.glb"], "--profile", "quest-webxr", "--project", ROOT / "proj3", "--renders", I["picture.png"], I["black.png"], I["palette.png"], I["picture_rgb.png"]], 1,
     ["render is blank"], env=env)
case("only two views -> not verified", [GATE, "check", M["cube.glb"], "--profile", "quest-webxr", "--project", ROOT / "proj3", "--renders", I["picture.png"], I["palette.png"]], 2,
     ["a turntable needs 4"], env=env)
case("a 16-bit render cannot be judged -> not verified", [GATE, "check", M["cube.glb"], "--profile", "quest-webxr", "--project", ROOT / "proj3", "--renders", *four, I["deep.png"]], 2,
     ["bit depth 16"], env=env)
case("same picture four times -> warning", [GATE, "check", M["cube.glb"], "--profile", "quest-webxr", "--project", ROOT / "proj3", "--renders", *([I["picture.png"]] * 4)], 0,
     ["check that the camera moved"], env=env)

print("#### gltf-gate: optimise and compare")
if shutil.which("gltf-transform"):
    print("note: a real gltf-transform is on PATH; the 'not installed' case is skipped")
else:
    case("optimiser missing -> blocked", [GATE, "optimise", M["cube.glb"], "--out", ROOT / "opt0.glb"], 2, ["blocked: gltf-transform not found"])
fake("gltf-transform", """import os, shutil, sys
mode = os.environ.get("FAKE_OPT", "copy")
source, target = sys.argv[2], sys.argv[3]
if mode == "copy":
    shutil.copy(source, target)
elif mode == "swap":
    shutil.copy(os.environ["FAKE_OTHER"], target)
elif mode == "damage-input":
    shutil.copy(source, target)
    open(source, "ab").write(b"x")
""")
case("optimiser stand-in copies -> pass", [GATE, "optimise", M["cube.glb"], "--out", ROOT / "opt1.glb"], 0, ["wrote"], env=env)
case("output already exists -> blocked", [GATE, "optimise", M["cube.glb"], "--out", ROOT / "opt1.glb"], 2, ["already exists"], env=env)
case("optimiser wrote nothing -> fail", [GATE, "optimise", M["cube.glb"], "--out", ROOT / "opt2.glb"], 1, ["wrote no output file"], env={**env, "FAKE_OPT": "none"})
case("optimiser changed the size -> fail", [GATE, "optimise", M["cube.glb"], "--out", ROOT / "opt3.glb"], 1, ["size along x changed"],
     env={**env, "FAKE_OPT": "swap", "FAKE_OTHER": str(M["two_boxes.glb"])})
victim = ROOT / "victim.glb"
shutil.copy(M["cube_plain.glb"], victim)
case("optimiser touched the input -> fail", [GATE, "optimise", victim, "--out", ROOT / "opt4.glb"], 1, ["changed the input file"], env={**env, "FAKE_OPT": "damage-input"})
case("renders agree", [GATE, "compare", "--before", I["picture.png"], "--after", I["picture_nudged.png"]], 0, ["same"])
case("renders differ", [GATE, "compare", "--before", I["picture.png"], "--after", I["picture_shifted.png"]], 1, ["DIFFERENT"])
case("renders of different size", [GATE, "compare", "--before", I["picture.png"], "--after", I["small.png"]], 2, ["sizes differ"])
case("uneven lists", [GATE, "compare", "--before", I["picture.png"], I["small.png"], "--after", I["small.png"]], 2, ["blocked"])
expect("the input cube.glb is byte-identical after all gate runs", sha(M["cube.glb"]) == cube_before)

print("#### pngstats")
sys.path.insert(0, str(PACK / "skills" / "three-verify" / "scripts"))
import pngstats  # noqa: E402

w, h, c, px = pngstats.decode(I["picture.png"])
expect("RGBA decode through all five row filters matches the source pixels",
       all(tuple(px[(y * w + x) * 4:(y * w + x) * 4 + 4]) == fixtures.picture(x, y) for x in range(w) for y in range(h)))
w, h, c, px = pngstats.decode(I["picture_rgb.png"])
expect("RGB decode matches", all(tuple(px[(y * w + x) * 3:(y * w + x) * 3 + 3]) == fixtures.picture(x, y)[:3] for x in range(w) for y in range(h)))
w, h, c, px = pngstats.decode(I["palette.png"])
table = [(0, 0, 0), (255, 0, 0), (0, 255, 0), (0, 0, 255)]
expect("palette decode matches", all(tuple(px[(y * w + x) * 4:(y * w + x) * 4 + 3]) == table[(x // 8 + y // 8) % 4] for x in range(w) for y in range(h)))
w, h, c, px = pngstats.decode(I["grey_alpha.png"])
expect("grey+alpha decode matches", all(px[(y * w + x) * 4] == (x * 4) % 256 and px[(y * w + x) * 4 + 3] == 255 for x in range(w) for y in range(h)))
for name, code, text in (("picture.png", 0, "picture"), ("picture_rgb.png", 0, "picture"), ("palette.png", 0, "picture"), ("grey_alpha.png", 0, "picture"),
                         ("black.png", 1, "flat"), ("grey.png", 1, "flat"), ("clear.png", 1, "transparent"), ("dot.png", 1, "single colour"),
                         ("deep.png", 2, "bit depth 16"), ("interlaced.png", 2, "interlaced"), ("not_a.png", 2, "not a PNG")):
    case(f"stats {name}", [PNG, "stats", I[name]], code, [text])
case("stats on a missing file", [PNG, "stats", ROOT / "none.png"], 2, ["cannot read"])
case("diff near-identical", [PNG, "diff", I["picture.png"], I["picture_nudged.png"]], 0, ["mean difference"])
case("diff different", [PNG, "diff", I["picture.png"], I["picture_shifted.png"]], 1, ["RESULT fail"])

print("#### three-verify: preflight")
PRE = skill("three-verify", "preflight.py")


def project(name, version=None, build="", src="", exports=None, declared="^0.160.0", addons=("controls/OrbitControls.js",), legacy_js=False):
    root = ROOT / name
    (root / "src").mkdir(parents=True)
    if declared:
        (root / "package.json").write_text(json.dumps({"dependencies": {"three": declared, "@react-three/fiber": "^9.0.0"}}))
    (root / "src" / "main.js").write_text(src)
    if version:
        three = root / "node_modules" / "three"
        (three / "build").mkdir(parents=True)
        (three / "package.json").write_text(json.dumps({"name": "three", "version": version, "exports": exports or {".": "./build/three.module.js"}}))
        (three / "build" / "three.module.js").write_text(build)
        for addon in addons:
            (three / "examples" / "jsm" / addon).parent.mkdir(parents=True, exist_ok=True)
            (three / "examples" / "jsm" / addon).write_text("export {}")
        if legacy_js:
            (three / "examples" / "js").mkdir(parents=True)
    return root


NEW_BUILD = "const SRGBColorSpace = 'srgb'; class WebGLRenderer { get outputColorSpace() {} }"
NEW_EXPORTS = {".": "./build/three.module.js", "./addons/*": "./examples/jsm/*"}
OLD_BUILD = "const sRGBEncoding = 3001; class WebGLRenderer { outputEncoding = 3000; physicallyCorrectLights = false }"
CLEAN = "import * as THREE from 'three';\nimport { OrbitControls } from 'three/addons/controls/OrbitControls.js';\nrenderer.outputColorSpace = THREE.SRGBColorSpace;\n"
case("no three.js at all -> blocked", [PRE, project("p_none", declared=None)], 2, ["blocked: no three.js here"])
case("declared but not installed -> not verified", [PRE, project("p_decl", src="renderer.outputEncoding = THREE.sRGBEncoding;\n")], 2,
     ["NOT installed", "2 lines match the unverified list"])
case("current code on r160 -> pass", [PRE, project("p_clean", "0.160.0", NEW_BUILD, CLEAN, NEW_EXPORTS)], 0, ["r160", "RESULT pass"])
case("old colour API on r160 -> fail, confirmed by the build", [PRE, project("p_old_api", "0.160.0", NEW_BUILD, "renderer.outputEncoding = THREE.sRGBEncoding;\n", NEW_EXPORTS)], 1,
     ["src/main.js:1", "does not occur in the installed build", "2 lines do not match"])
case("addon that is not in the package -> fail", [PRE, project("p_addon", "0.160.0", NEW_BUILD, "import { X } from 'three/addons/controls/NoSuch.js';\n", NEW_EXPORTS)], 1,
     ["is not in the installed package"])
case("examples/js path on r160 -> fail", [PRE, project("p_js", "0.160.0", NEW_BUILD, "<script src='node_modules/three/examples/js/controls/OrbitControls.js'>\n", NEW_EXPORTS)], 1,
     ["the installed package has no examples/js/"])
case("new colour API on r140 -> fail", [PRE, project("p_new_on_old", "0.140.0", OLD_BUILD, "renderer.outputColorSpace = THREE.SRGBColorSpace;\n", declared="^0.140.0", legacy_js=True)], 1,
     ["listed as added in r152"])
case("three/addons alias on r140 -> fail", [PRE, project("p_alias_old", "0.140.0", OLD_BUILD, "import { OrbitControls } from 'three/addons/controls/OrbitControls.js';\n", declared="^0.140.0", legacy_js=True)], 1,
     ["exports no './addons/*'"])
case("old API on r140 -> pass", [PRE, project("p_old_ok", "0.140.0", OLD_BUILD, "renderer.outputEncoding = THREE.sRGBEncoding;\n", declared="^0.140.0", legacy_js=True)], 0, ["RESULT pass"])
case("deprecated but still in the build -> note, pass", [PRE, project("p_shim", "0.155.0", NEW_BUILD + " outputEncoding sRGBEncoding", "renderer.outputEncoding = THREE.sRGBEncoding;\n", NEW_EXPORTS)], 0,
     ["probably deprecated, not broken"])
case("not a folder -> blocked", [PRE, ROOT / "no_such_project"], 2, ["blocked"])

print("#### three-verify: capture report checker")
CAP = skill("three-verify", "check_capture.py")
caps = ROOT / "captures"
caps.mkdir()
shutil.copy(I["picture.png"], caps / "front.png")
shutil.copy(I["picture_shifted.png"], caps / "side.png")
shutil.copy(I["black.png"], caps / "black.png")
GOOD = {
    "adapter": {"vendor": "Example", "renderer": "ANGLE (Example GPU, Metal)"},
    "poses": [{"name": "front", "screenshot": "front.png"}, {"name": "side", "screenshot": "side.png"}],
    "console_errors": [],
    "counters": {"before": {"calls": 0, "triangles": 0, "geometries": 0, "textures": 0, "programs": 0},
                 "loaded": {"calls": 42, "triangles": 90000, "geometries": 30, "textures": 12, "programs": 6},
                 "after_dispose": {"calls": 0, "triangles": 0, "geometries": 0, "textures": 0, "programs": 6}},
    "frame_time_ms": None,
}


def report(name, **changes):
    data = json.loads(json.dumps(GOOD))
    for key, value in changes.items():
        if value is None and key != "frame_time_ms":
            data.pop(key, None)
        else:
            data[key] = value
    path = caps / f"{name}.json"
    path.write_text(json.dumps(data))
    return path


SOFT = {"vendor": "Google Inc.", "renderer": "ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero)), SwiftShader driver)"}
FT = {"median": 8.1, "p95": 11.0, "samples": 120}
counters = lambda **kw: {**GOOD["counters"], **kw}  # noqa: E731
case("good capture -> pass", [CAP, report("good")], 0, ["decoded from the file", "frame time not measured", "RESULT pass"])
case("black screenshot -> fail", [CAP, report("blank", poses=[{"name": "front", "screenshot": "black.png"}])], 1, ["BLANK", "pose front is blank"])
case("page-reported flat pixels -> fail", [CAP, report("flat", poses=[{"name": "front", "pixels": {"spread": 0.0, "dominant_share": 1.0, "transparent_share": 0.0}}])], 1, ["numbers reported by the page"])
case("screenshot file wins over page numbers", [CAP, report("lie", poses=[{"name": "front", "screenshot": "black.png", "pixels": {"spread": 60.0, "dominant_share": 0.1, "transparent_share": 0.0}}])], 1, ["decoded from the file"])
case("screenshot missing, page numbers fine -> pass, labelled", [CAP, report("nofile", poses=[{"name": "front", "screenshot": "gone.png", "pixels": {"spread": 60.0, "dominant_share": 0.1, "transparent_share": 0.0}}])], 0, ["screenshot gone.png not found"])
case("console errors -> fail", [CAP, report("console", console_errors=["THREE.WebGLProgram: shader error"])], 1, ["1 console errors"])
case("draw calls over budget -> fail", [CAP, report("over", counters=counters(loaded={"calls": 5000, "triangles": 10, "geometries": 1, "textures": 1, "programs": 1}))], 1, ["calls 5000 is over"])
case("textures left after dispose -> fail", [CAP, report("leak", counters=counters(after_dispose={"calls": 0, "triangles": 0, "geometries": 0, "textures": 9, "programs": 6}))], 1, ["9 textures are still in memory"])
case("software renderer with a frame time -> fail", [CAP, report("soft_ft", adapter=SOFT, frame_time_ms=FT)], 1, ["software renderer"])
case("software renderer, flag says frame time will be claimed -> fail", [CAP, report("soft_claim", adapter=SOFT), "--claims-frame-time"], 1, ["software renderer"])
case("software renderer, no frame time claimed -> pass", [CAP, report("soft_ok", adapter=SOFT)], 0, ["<- software renderer", "RESULT pass"])
case("frame time without an adapter name -> not verified", [CAP, report("no_adapter", adapter=None, frame_time_ms=FT)], 2, ["adapter name was not read"])
case("frame time over the 72 Hz budget -> fail", [CAP, report("slow", frame_time_ms={"median": 20.0, "p95": 30.0, "samples": 120}), "--refresh-hz", "72"], 1, ["over the 13.89 ms budget"])
case("frame time inside the 72 Hz budget -> pass", [CAP, report("fast", frame_time_ms=FT), "--refresh-hz", "72"], 0, ["RESULT pass"])
case("no poses -> not verified", [CAP, report("no_poses", poses=[])], 2, ["no camera pose was captured"])
case("no dispose step -> not verified", [CAP, report("no_dispose", counters={"loaded": GOOD["counters"]["loaded"]})], 2, ["leak check"])
case("console not recorded -> not verified", [CAP, report("no_console", console_errors=None)], 2, ["console errors were not recorded"])
(caps / "junk.json").write_text("not json")
case("unreadable report -> not verified", [CAP, caps / "junk.json"], 2, ["cannot read"])
case("unknown profile -> blocked", [CAP, report("good2"), "--profile", "nope"], 2, ["blocked"])

print("#### three-verify: the in-page snippet under Node with a mock renderer (no browser)")
node = shutil.which("node")
if not node:
    print("not run: node is not installed")
else:
    harness = ROOT / "snippet_harness.js"
    harness.write_text("""
const cap = require(process.argv[2]);
const assert = require('assert');
const flat = new Uint8Array(64 * 48 * 4).fill(7);
const s1 = cap.pixelStats(flat, 64, 48);
assert.strictEqual(s1.spread, 0); assert.strictEqual(s1.dominant_share, 1);
const noisy = new Uint8Array(64 * 48 * 4);
for (let i = 0; i < noisy.length; i++) noisy[i] = (i * 37 + (i >> 3) * 11) % 256;
const s2 = cap.pixelStats(noisy, 64, 48);
assert.ok(s2.spread > 20 && s2.dominant_share < 0.5, JSON.stringify(s2));
assert.strictEqual(cap.pixelStats(new Uint8Array(4), 64, 48), null);
const gl = { VENDOR: 1, RENDERER: 2, RGBA: 3, UNSIGNED_BYTE: 4, drawingBufferWidth: 64, drawingBufferHeight: 48,
  getExtension: () => ({ UNMASKED_VENDOR_WEBGL: 10, UNMASKED_RENDERER_WEBGL: 11 }),
  getParameter: (p) => ({ 10: 'Mock Vendor', 11: 'Mock GPU (mock, not a real adapter)' })[p],
  readPixels: (x, y, w, h, f, t, buf) => buf.set(noisy) };
let renders = 0;
const renderer = { getContext: () => gl, render: () => { renders++; },
  info: { render: { calls: 12, triangles: 3400 }, memory: { geometries: 5, textures: 2 }, programs: [1, 2, 3] } };
(async () => {
  const run = cap.start({ renderer, scene: {}, camera: {}, THREE: { REVISION: '160' } });
  renderer.info.memory = { geometries: 0, textures: 0 }; run.mark('before');
  renderer.info.memory = { geometries: 5, textures: 2 };
  let posed = 0;
  await run.pose('front', () => { posed++; });
  await run.pose('side', () => { posed++; });
  run.mark('loaded');
  renderer.info.memory = { geometries: 0, textures: 0 }; run.mark('after_dispose');
  const report = run.report();
  assert.strictEqual(posed, 2); assert.strictEqual(renders, 2);
  assert.strictEqual(report.poses.length, 2);
  assert.strictEqual(report.adapter.renderer, 'Mock GPU (mock, not a real adapter)');
  assert.deepStrictEqual(report.counters.loaded, { calls: 12, triangles: 3400, geometries: 5, textures: 2, programs: 3 });
  assert.strictEqual(report.three_revision, '160');
  require('fs').writeFileSync(process.argv[3], JSON.stringify(report));
  console.error('boom from the page');
  assert.strictEqual(run.report().console_errors.length, 1);
  console.log('snippet assertions passed');
})().catch((e) => { console.log('ASSERTION FAILED ' + e.message); process.exit(1); });
""")
    out = subprocess.run([node, str(harness), skill("three-verify", "capture_snippet.js"), str(caps / "from_snippet.json")], capture_output=True, text=True)
    expect("snippet: pixel statistics, adapter, counters, console hook (Node, mock GL)", out.returncode == 0 and "snippet assertions passed" in out.stdout, out.stdout + out.stderr)
    case("a report made by the snippet is accepted by the checker", [CAP, caps / "from_snippet.json"], 0, ["numbers reported by the page", "poses front, side gave the same image", "RESULT pass"])

print("#### rig-motion-check")
MOT = skill("rig-motion-check", "motion.py")
RIG = M["rig.glb"]
case("list bones and clips", [MOT, "list", RIG], 0, ["Foot_L  <- foot or hand?", "clip 0 'planted': 1.000 s", "CUBICSPLINE"])
case("list a model with no rig -> not verified", [MOT, "list", M["cube.glb"]], 2, ["no skin and no animation"])
case("planted foot -> pass", [MOT, "check", RIG, "--joint", "Foot_L", "--clip", "planted"], 0, ["worst slide in one contact 0.0000 m", "not computed by this script", "RESULT pass"])
case("foot slides 0.6 m in contact -> fail", [MOT, "check", RIG, "--joint", "Foot_L", "--clip", "slide"], 1, ["bone slides 0.6000 m while in contact"])
case("same clip declared in-place -> pass", [MOT, "check", RIG, "--joint", "Foot_L", "--clip", "slide", "--in-place"], 0, ["not judged: --in-place"])
case("foot sinks 0.1 m -> fail", [MOT, "check", RIG, "--joint", "Foot_L", "--clip", "sink"], 1, ["0.1000 m under the floor"])
table = ROOT / "swing.json"
case("hip rotation moves the foot (forward kinematics)", [MOT, "check", RIG, "--joint", "Foot_L", "--clip", "swing", "--json-out", table], 1, ["bone slides"])
rows = {r["t"]: r["pos"] for r in json.loads(table.read_text())["clips"][0]["samples"]}
expect("FK numbers: 90 degrees about Z puts the foot at (1, 1, 0); 45 degrees at (0.7071, 0.2929, 0)",
       all(abs(a - b) < 1e-4 for a, b in zip(rows[1.0], (1, 1, 0))) and all(abs(a - b) < 1e-4 for a, b in zip(rows[0.5], (0.70711, 0.29289, 0))), str((rows[1.0], rows[0.5])))
case("table file is not overwritten", [MOT, "check", RIG, "--joint", "Foot_L", "--clip", "swing", "--json-out", table], 2, ["already exists"])
case("a real step: lift, travel, land -> pass", [MOT, "check", RIG, "--joint", "Foot_L", "--clip", "step"], 0, ["RESULT pass"])
case("scale animated on the hips -> fail", [MOT, "check", RIG, "--joint", "Foot_L", "--clip", "grow"], 1, ["scale drifts 20.00%"])
case("cubic spline clip -> pass with note", [MOT, "check", RIG, "--joint", "Foot_L", "--clip", "spline"], 0, ["cubic spline channels"])
case("every clip at once -> fail, names the clips", [MOT, "check", RIG, "--joint", "Foot_L"], 1, ["RESULT fail: slide, sink, swing, grow"])
case("floor stated too high -> fail", [MOT, "check", RIG, "--joint", "Foot_L", "--clip", "planted", "--floor", "0.5"], 1, ["under the floor"])
case("floor stated too low -> not verified", [MOT, "check", RIG, "--joint", "Foot_L", "--clip", "planted", "--floor", "-1"], 2, ["no contact found"])
case("clip does not move this bone -> not verified", [MOT, "check", RIG, "--joint", "Hips", "--clip", "step"], 2, ["does not move the bone"])
case("no such bone -> blocked, suggests", [MOT, "check", RIG, "--joint", "Hand_R"], 2, ["blocked: no bone named 'Hand_R'", "Foot_L"])
case("ambiguous bone -> blocked", [MOT, "check", RIG, "--joint", "_L"], 2, ["matches 2 bones"])
case("no such clip -> blocked", [MOT, "check", RIG, "--joint", "Foot_L", "--clip", "run"], 2, ["blocked: no clip"])
case("model without animation -> not verified", [MOT, "check", M["cube.glb"], "--joint", "Box"], 2, ["no animation clips"])
case("broken file -> fail", [MOT, "check", M["bad_accessor.glb"], "--joint", "x"], 1, ["structural errors"])
case("not a model -> not verified", [MOT, "list", M["error_page.glb"]], 2, ["RESULT not verified"])

print("#### blender-task")
BL = skill("blender-task", "blender_job.py")
blender_here = shutil.which("blender") or any(pathlib.Path(p).expanduser().exists() for p in ("/Applications/Blender.app", "~/Applications/Blender.app"))
no_env = {k: v for k, v in os.environ.items() if k != "BLENDER_BIN"}
out = subprocess.run([sys.executable, BL, "detect"], capture_output=True, text=True, env=no_env)
expect(f"detect on this machine: exit {out.returncode}, Blender {'present' if blender_here else 'absent'}", out.returncode == (0 if blender_here else 2), out.stdout)
case("explicit path that does not exist -> blocked", [BL, "--blender", ROOT / "no" / "blender", "detect"], 2, ["blocked: no runnable program"])
fake("blender", """import json, os, sys
if "--version" in sys.argv:
    print("Blender 9.9.9 (stand-in for tests)" if os.environ.get("FAKE_BLENDER") != "impostor" else "hello, I am another program")
    sys.exit(0)
mode = os.environ.get("FAKE_BLENDER", "ok")
argv = sys.argv[1:]
state = argv[argv.index("--mstack-state") + 1]
assert "--background" in argv and argv.count("--python") == 2, argv
if mode == "crash":
    print("Error: Python: Traceback ... NameError in job", file=sys.stderr)
    sys.exit(1)
if mode == "touch-blend":
    blend = next(a for a in argv if a.endswith(".blend"))
    open(blend, "ab").write(b"changed")
if mode != "nostate":
    json.dump({"blender_version": "9.9.9 stand-in", "unit_scale": 1.0, "objects": [
        {"name": "Table", "type": "MESH", "dimensions": [1.2, 0.6, 0.75], "scale": [1, 1, 1], "modifiers": [], "polygons": 96}]}, open(state, "w"))
""")
job = ROOT / "job.py"
job.write_text("# a Blender job script would go here; the stand-in does not run it\n")
blend = ROOT / "scene.blend"
blend.write_bytes(b"BLENDER-stand-in-file")
FB = BIN / "blender"
case("detect a stand-in Blender", [BL, "--blender", FB, "detect"], 0, ["Blender 9.9.9 (stand-in for tests)"])
case("a program that is not Blender -> blocked", [BL, "--blender", FB, "detect"], 2, ["does not answer like Blender"], env={"FAKE_BLENDER": "impostor"})
case("run with the stand-in -> state file", [BL, "--blender", FB, "run", "--job", job, "--state", ROOT / "st1.json", "--blend", blend], 0, ["1 objects", "Table"])
case("state file is never overwritten -> blocked", [BL, "--blender", FB, "run", "--job", job, "--state", ROOT / "st1.json"], 2, ["already exists"])
case("exit 0 but no state file -> fail", [BL, "--blender", FB, "run", "--job", job, "--state", ROOT / "st2.json"], 1, ["wrote no state file"], env={"FAKE_BLENDER": "nostate"})
case("job raised an error -> fail", [BL, "--blender", FB, "run", "--job", job, "--state", ROOT / "st3.json"], 1, ["exited with code 1"], env={"FAKE_BLENDER": "crash"})
case("job changed the .blend -> fail", [BL, "--blender", FB, "run", "--job", job, "--state", ROOT / "st4.json", "--blend", blend], 1, ["changed"], env={"FAKE_BLENDER": "touch-blend"})
case("missing job script -> blocked", [BL, "--blender", FB, "run", "--job", ROOT / "nojob.py", "--state", ROOT / "st5.json"], 2, ["blocked: job script"])
case("run without Blender -> blocked", [BL, "--blender", ROOT / "no" / "blender", "run", "--job", job, "--state", ROOT / "st6.json"], 2, ["blocked"])

STATE = {"blender_version": "hand-written", "unit_scale": 1.0, "objects": [
    {"name": "Table", "type": "MESH", "dimensions": [1.2, 0.6, 0.75], "scale": [1.0, 1.0, 1.0], "polygons": 96, "polygons_evaluated": 384,
     "modifiers": [], "materials": ["Oak"], "uv_layers": 1, "parent": None},
    {"name": "Lamp", "type": "LIGHT", "dimensions": [0, 0, 0], "scale": [1, 1, 1], "modifiers": []}]}
FACTS = {"objects": [{"name": "Table", "type": "MESH", "dimensions_m": [1.2, 0.6, 0.75], "tolerance_m": 0.005, "polygons_max": 5000,
                      "polygons_min": 12, "modifiers_none": True, "scale_applied": True, "materials_min": 1, "uv_layers_min": 1}],
         "absent": ["Cube"], "count": {"MESH": 1}}


def pair(name, state=None, facts=None):
    s, f = ROOT / f"{name}_state.json", ROOT / f"{name}_facts.json"
    s.write_text(json.dumps(state if state is not None else STATE))
    f.write_text(json.dumps(facts if facts is not None else FACTS))
    return ["--state", s, "--facts", f]


def table_with(**changes):
    data = json.loads(json.dumps(STATE))
    data["objects"][0].update(changes)
    return data


case("hand-written state matches every fact -> pass", [BL, "check", *pair("ok")], 0, ["11 facts hold", "RESULT pass"])
case("wrong height -> fail", [BL, "check", *pair("dims", table_with(dimensions=[1.2, 0.6, 0.9]))], 1, ["Table: dimensions in metres"])
case("scale not applied -> fail", [BL, "check", *pair("scale", table_with(scale=[2.0, 1.0, 1.0]))], 1, ["Table: scale applied"])
case("modifier left on the object -> fail", [BL, "check", *pair("mods", table_with(modifiers=[{"name": "Bevel", "type": "BEVEL"}]))], 1, ["no modifiers left"])
case("polygon count after modifiers over the limit -> fail", [BL, "check", *pair("poly", table_with(polygons_evaluated=9000))], 1, ["polygons_max"])
case("default cube still there -> fail", [BL, "check", *pair("cube", {**STATE, "objects": STATE["objects"] + [{"name": "Cube", "type": "LIGHT"}]})], 1, ["Cube: absent"])
case("object missing -> fail", [BL, "check", *pair("gone", {**STATE, "objects": STATE["objects"][1:]})], 1, ["Table: exists"])
case("wanted modifier present -> pass", [BL, "check", *pair("want", table_with(modifiers=[{"name": "B", "type": "BEVEL"}]), {"objects": [{"name": "Table", "modifiers": ["BEVEL"]}]})], 0, ["RESULT pass"])
case("state in centimetre units -> converted, pass", [BL, "check", *pair("cm", {**table_with(dimensions=[120, 60, 75]), "unit_scale": 0.01})], 0, ["unit scale 0.01"])
case("state lacks a value -> not verified", [BL, "check", *pair("lack", {"objects": [{"name": "Table", "type": "MESH"}]}, {"objects": [{"name": "Table", "polygons_max": 10, "scale_applied": True}]})], 2, ["the state file lacks"])
case("no facts -> not verified, never a pass", [BL, "check", *pair("empty", facts={})], 2, ["nothing was checked"])
(ROOT / "junk_state.json").write_text("{")
case("unreadable state -> not verified", [BL, "check", "--state", ROOT / "junk_state.json", "--facts", ROOT / "ok_facts.json"], 2, ["cannot read"])
expect("assets/state_dump.py parses as Python (it cannot run here: no Blender)",
       compile((PACK / "skills" / "blender-task" / "assets" / "state_dump.py").read_text(), "state_dump.py", "exec") is not None)

print("#### text-to-3d")
ACC = skill("text-to-3d", "accept.py")
tp = ROOT / "t3d"
tp.mkdir()
case("no approval flag -> blocked, nothing recorded", [ACC, "--project", tp, "approve", "--provider", "ExampleGen", "--cost", "about 0.40 USD per model", "--prompt", "a wooden stool"], 2, ["blocked: no approval recorded"])
expect("no record exists after the refusal", not (tp / ".mstack").exists())
case("empty cost -> blocked", [ACC, "--project", tp, "approve", "--provider", "ExampleGen", "--cost", " ", "--prompt", "a wooden stool", "--user-approved"], 2, ["blocked"])


def approve():
    text = case("approval recorded", [ACC, "--project", tp, "approve", "--provider", "ExampleGen", "--cost", "about 0.40 USD per model", "--prompt", "a wooden stool", "--user-approved"], 0, ["one generation"])
    return text.split("approval ")[1].split(":")[0]


first = approve()
case("accept without a known approval -> blocked", [ACC, "--project", tp, "accept", M["cube.glb"], "--id", "t3d-none", "--profile", "phone-ar"], 2, ["blocked: no approval record"])
case("downloaded an error page -> rejected", [ACC, "--project", tp, "accept", M["error_page.glb"], "--id", first, "--profile", "phone-ar"], 1, ["not a model file", "Download the same result again"])
case("missing download -> blocked", [ACC, "--project", tp, "accept", ROOT / "nofile.glb", "--id", first, "--profile", "phone-ar"], 2, ["no such file"])
case("real model, gate not run yet -> not verified", [ACC, "--project", tp, "accept", M["cube.glb"], "--id", first, "--profile", "phone-ar"], 2, ["the full gate has not passed"])
case("gate passes for this file (stand-in validator, real pictures)", [GATE, "check", M["cube.glb"], "--profile", "phone-ar", "--project", tp, "--renders", *four], 0, ["RESULT pass"], env=env)
case("same file again, gate manifest found -> accepted", [ACC, "--project", tp, "accept", M["cube.glb"], "--id", first, "--profile", "phone-ar"], 0, ["manifest for this exact file says pass", "RESULT pass"])
case("a second file on the same approval -> blocked", [ACC, "--project", tp, "accept", M["two_boxes.glb"], "--id", first, "--profile", "phone-ar"], 2, ["already covered one generated file"])
second = approve()
case("over budget -> rejected", [ACC, "--project", tp, "accept", M["cube_plain.glb"], "--id", second, "--profile", "tiny", "--budgets", tight], 1, ["triangles 12 is over the tiny budget of 10"])
third = approve()
case("structural error -> rejected", [ACC, "--project", tp, "accept", M["bad_accessor.glb"], "--id", third, "--profile", "phone-ar"], 1, ["structural errors"])
case("unknown profile -> blocked", [ACC, "--project", tp, "accept", M["cube.glb"], "--id", first, "--profile", "nope"], 2, ["blocked: no budget profile"])
case("ledger lists three approvals with cost", [ACC, "--project", tp, "list"], 0, ["3 approvals recorded", "about 0.40 USD per model", "accepted", "rejected"])
case("ledger of an untouched project", [ACC, "--project", ROOT / "proj", "list"], 0, ["nothing was spent"])

failed = results.count(False)
print(f"\n{len(results)} checks, {failed} failed")
sys.exit(1 if failed else 0)

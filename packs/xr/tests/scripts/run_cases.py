"""Script tests for the mstack-xr pack. Builds throwaway projects and files, runs each script, compares exit codes.

Usage: run_cases.py <new folder under .testrun/>
Model and image fixtures come from the 3d pack's tests/scripts/fixtures.py when that pack sits beside this one
(only the test reuses it; the skills themselves carry their own copies).
"""
import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
PACK = HERE.parent.parent
sys.path.insert(0, str(PACK.parent / "3d" / "tests" / "scripts"))
import fixtures  # noqa: E402

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("folder", type=pathlib.Path)
args = parser.parse_args()
if args.folder.exists():
    sys.exit(f"refusing: {args.folder} already exists")
ROOT = args.folder.resolve()
M = fixtures.write_models(ROOT / "models")
I = fixtures.write_images(ROOT / "images")
results = []


def skill(name, script):
    return str(PACK / "skills" / name / "scripts" / script)


def case(name, command, expect, contains=(), env=None):
    out = subprocess.run([sys.executable, *map(str, command)], capture_output=True, text=True, env={**os.environ, **(env or {})}, cwd=ROOT)
    text = out.stdout + out.stderr
    missing = [c for c in contains if c not in text]
    ok = out.returncode == expect and not missing
    results.append(ok)
    print(f"{'ok  ' if ok else 'FAIL'} {name}: exit {out.returncode} (expect {expect})" + (f" missing {missing}" if missing else ""))
    if not ok:
        print("     | " + "\n     | ".join(text.strip().splitlines()[-6:]))
    return text


def expect(name, condition, detail=""):
    results.append(bool(condition))
    print(f"{'ok  ' if condition else 'FAIL'} {name}" + (f": {detail}" if detail and not condition else ""))


def write(path, text):
    path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


sha = lambda p: hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()  # noqa: E731
expect("glb.py in webar-preview equals the 3d gltf-gate copy", sha(skill("webar-preview", "glb.py")) == sha(PACK.parent / "3d/skills/gltf-gate/scripts/glb.py"))
expect("pngstats.py in webxr-verify equals the 3d three-verify copy", sha(skill("webxr-verify", "pngstats.py")) == sha(PACK.parent / "3d/skills/three-verify/scripts/pngstats.py"))

print("#### webxr-verify: static scan")
SCAN = skill("webxr-verify", "xr_scan.py")
FULL = """import * as THREE from 'three';
renderer.xr.enabled = true;
if (await navigator.xr.isSessionSupported('immersive-vr')) button.hidden = false;
const session = await navigator.xr.requestSession('immersive-vr', { optionalFeatures: ['hand-tracking'] });
renderer.setAnimationLoop(render);
const c = renderer.xr.getController(0); c.addEventListener('select', fire);
const hand = renderer.xr.getHand(0);
exitButton.onclick = () => session.end();
"""
write("full/src/main.js", FULL)
write("full/vite.config.js", "export default { server: { https: true } }")
case("complete VR page -> pass", [SCAN, ROOT / "full", "--mode", "vr"], 0, ["session request (vr): src/main.js:4", "https setup seen in vite.config.js"])
case("same page asked for AR -> fail", [SCAN, ROOT / "full", "--mode", "ar"], 1, ["missing session request (ar)"])
write("noloop/src/main.js", FULL.replace("renderer.setAnimationLoop(render);", "requestAnimationFrame(render);"))
case("window.requestAnimationFrame only -> fail", [SCAN, ROOT / "noloop"], 1, ["render loop that runs in XR"])
write("thin/src/main.js", "renderer.xr.enabled = true;\nnavigator.xr.requestSession('immersive-vr').then(s => renderer.xr.setSession(s));\nrenderer.setAnimationLoop(draw);\n")
case("no input, no exit, no https -> pass with warnings", [SCAN, ROOT / "thin"], 0, ["warn  controller input", "warn  hand input", "warn  exit path", "No https setup"])
write("aframe/index.html", "<html><body><a-scene><a-entity laser-controls hand-tracking-controls></a-entity></a-scene></body></html>")
case("A-Frame page -> pass, framework named", [SCAN, ROOT / "aframe"], 0, ["framework that manages the session"])
write("plain/src/app.js", "console.log('no xr here')\n")
case("no XR at all -> fail", [SCAN, ROOT / "plain"], 1, ["missing session request"])
(ROOT / "empty").mkdir()
case("no source files -> blocked", [SCAN, ROOT / "empty"], 2, ["blocked"])

print("#### webxr-verify: session report checker")
CHK = skill("webxr-verify", "check_session.py")
caps = ROOT / "caps"
caps.mkdir()
for name in ("picture", "picture_rgb", "picture_shifted", "palette", "black"):
    shutil.copy(I[f"{name}.png"], caps / f"{name}.png")
GOOD = {"emulator": "test stand-in", "session": {"started": True, "mode": "immersive-vr", "ended": True},
        "adapter": {"renderer": "ANGLE (Example GPU, Metal)"}, "console_errors": [], "counters": {"calls": 40, "triangles": 50000},
        "captures": [{"kind": "pose", "name": "front", "screenshot": "picture.png"}, {"kind": "pose", "name": "left", "screenshot": "picture_rgb.png"},
                     {"kind": "pose", "name": "right", "screenshot": "picture_shifted.png"}, {"kind": "input", "name": "controllers", "screenshot": "palette.png"},
                     {"kind": "input", "name": "hands", "pixels": {"spread": 40.0, "dominant_share": 0.2, "transparent_share": 0.0}}]}


def rep(name, **changes):
    data = json.loads(json.dumps(GOOD))
    data.update(changes)
    path = caps / f"{name}.json"
    path.write_text(json.dumps(data))
    return path


case("good emulated session -> pass, lists limits", [CHK, rep("good")], 0, ["what an emulator cannot prove", "real frame rate", "RESULT pass"])
case("session did not start -> fail", [CHK, rep("nostart", session={"started": False, "error": "NotSupportedError"})], 1, ["no XR session started (NotSupportedError)"])
case("AR session when VR asked -> fail", [CHK, rep("mode", session={"started": True, "mode": "immersive-ar"})], 1, ["expected immersive-vr"])
bad = json.loads(json.dumps(GOOD["captures"]))
bad[1]["screenshot"] = "black.png"
case("one black pose -> fail", [CHK, rep("black", captures=bad)], 1, ["pose left is blank"])
case("hands never captured -> fail", [CHK, rep("nohands", captures=GOOD["captures"][:4])], 1, ["no capture for input hands"])
case("hands not required -> pass", [CHK, rep("nohands2", captures=GOOD["captures"][:4]), "--inputs", "controllers"], 0, ["RESULT pass"])
case("console error -> fail", [CHK, rep("console", console_errors=["WebGL: INVALID_OPERATION"])], 1, ["1 console errors"])
case("draw calls over the limit -> fail", [CHK, rep("calls", counters={"calls": 900, "triangles": 10})], 1, ["calls 900 is over 100"])
case("adapter not read -> not verified", [CHK, rep("noadapter", adapter={})], 2, ["GPU adapter name not read"])
case("emulator frame time is refused", [CHK, rep("ft", frame_time_ms={"median": 5})], 0, ["NOT accepted"])
(caps / "junk.json").write_text("[")
case("unreadable report -> not verified", [CHK, caps / "junk.json"], 2, ["cannot read"])
if shutil.which("node"):
    harness = write("snip.js", "const x=require(process.argv[2]);const f=new Uint8Array(16*16*4).fill(9);const s=x.stats(f,16,16);"
                    "if(s.spread!==0||s.dominant_share!==1)process.exit(1);const n=new Uint8Array(16*16*4);for(let i=0;i<n.length;i++)n[i]=(i*53)%256;"
                    "const t=x.stats(n,16,16);if(!(t.spread>20))process.exit(1);console.log('ok');")
    out = subprocess.run(["node", str(harness), skill("webxr-verify", "session_snippet.js")], capture_output=True, text=True)
    expect("session snippet pixel statistics under Node (no browser, no emulator)", out.returncode == 0, out.stderr)

print("#### xr-comfort-review")
CMF = skill("xr-comfort-review", "comfort.py")
HEAD = {"position": [0, 1.6, 0], "forward": [0, 0, -2]}


def dump(name, elements, head=HEAD):
    return write(f"dumps/{name}.json", json.dumps({"head": head, "elements": elements}))


ok_panel = {"name": "menu", "position": [0, 1.6, -1.5], "size": [0.8, 0.5], "text_height": 0.04, "interactive": True}
case("panel at 1.5 m straight ahead -> pass", [CMF, dump("ok", [ok_panel])], 0, ["text angle deg", "1.53", "RESULT pass"])
case("panel 0.3 m from the eyes -> fail", [CMF, dump("near", [{**ok_panel, "position": [0, 1.6, -0.3]}])], 1, ["menu: distance m 0.30"])
case("tiny text at 3 m -> fail", [CMF, dump("tiny", [{**ok_panel, "position": [0, 1.6, -3], "text_height": 0.01}])], 1, ["text angle deg 0.19"])
case("panel 60 degrees to the side -> fail", [CMF, dump("side", [{**ok_panel, "position": [1.299, 1.6, -0.75]}])], 1, ["offset from forward deg 60.0"])
case("head-locked HUD 30 degrees off -> fail, 30 world-locked -> pass",
     [CMF, dump("hud", [{"name": "hud", "position": [0, 1.6 + 0.866 * 0, -1], "head_locked": True}, {"name": "sign", "position": [0.577, 1.6, -1.0]}],
                {"position": [0, 1.6, 0], "forward": [0.5, 0, -0.866]})], 1, ["hud: offset from forward deg (head-locked) 30.0"])
case("small button at 2 m -> fail", [CMF, dump("button", [{"name": "ok button", "position": [0, 1.6, -2], "size": [0.04, 0.03], "interactive": True}])], 1, ["target angle deg 0.86"])
case("missing size and text height -> not verified, never ok",
     [CMF, dump("skip", [{"name": "label", "position": [0, 1.6, -1.5], "has_text": True, "interactive": True}])], 2, ["skipped", "2 checks skipped"])
case("no elements -> not verified", [CMF, dump("none", [])], 2, ["nothing was measured"])
case("no head -> not verified", [CMF, write("dumps/nohead.json", json.dumps({"elements": [ok_panel]}))], 2, ["no head position"])
if shutil.which("node"):
    harness = write("dumpharness.js", """
const dump = require(process.argv[2]);
class V { constructor(x=0,y=0,z=0){this.x=x;this.y=y;this.z=z;} }
const THREE = { Vector3: V, Box3: class { setFromObject(o){this.o=o;return this;} getCenter(v){Object.assign(v,o2v(this.o.c));} getSize(v){Object.assign(v,o2v(this.o.s));} } };
function o2v(a){return {x:a[0],y:a[1],z:a[2]};}
const camera = { updateMatrixWorld(){}, getWorldPosition(v){Object.assign(v,{x:0,y:1.6,z:0});}, getWorldDirection(v){Object.assign(v,{x:0,y:0,z:-1});} };
const hud = { userData:{mstackUi:{name:'hud',textHeight:0.01}}, parent: camera, c:[0,1.6,-1], s:[0.3,0.1,0.01], getWorldScale(v){Object.assign(v,{x:1,y:2,z:1});} };
const panel = { userData:{mstackUi:{name:'panel',interactive:true}}, parent: null, c:[0,1.5,-2], s:[1,0.6,0.02], getWorldScale(v){Object.assign(v,{x:1,y:1,z:1});} };
const scene = { updateMatrixWorld(){}, traverse(f){ [hud, panel, {userData:{}}].forEach(f); } };
const d = dump(scene, camera, THREE);
if (d.elements.length !== 2 || !d.elements[0].head_locked || d.elements[0].text_height !== 0.02 || d.elements[1].size[0] !== 1) { console.log(JSON.stringify(d)); process.exit(1); }
require('fs').writeFileSync(process.argv[3], JSON.stringify(d)); console.log('ok');
""")
    out = subprocess.run(["node", str(harness), skill("xr-comfort-review", "scene_dump.js"), str(ROOT / "dumps/from_snippet.json")], capture_output=True, text=True)
    expect("scene_dump.js under Node with a mock scene: head-locked flag, scaled text height, sizes", out.returncode == 0, out.stdout + out.stderr)
    case("a dump made by the snippet runs through comfort.py (hud text 0.02 m at 1 m = 1.15 deg)", [CMF, ROOT / "dumps/from_snippet.json"], 0, ["1.15", "panel", "RESULT pass"])

print("#### xr-target")
TGT = skill("xr-target", "target.py")
write("t_three/package.json", '{"dependencies": {"three": "^0.160.0"}}')
write("t_three/src/main.js", "renderer.xr.enabled = true;\ndocument.body.appendChild(VRButton.createButton(renderer));\n")
case("three.js WebXR repo", [TGT, ROOT / "t_three"], 0, ["three.js WebXR", "version  three ^0.160.0", "webxr-verify"])
write("t_unity/Packages/manifest.json", '{"dependencies": {"com.meta.xr.sdk.core": "71.0.0", "com.unity.xr.openxr": "1.13.0"}}')
write("t_unity/Android/AndroidManifest.xml", '<category android:name="com.oculus.intent.category.VR" />')
case("Unity Quest repo -> points to Meta's skills", [TGT, ROOT / "t_unity"], 0, ["Unity Meta XR SDK", "Android VR headset (Quest)", "Meta's own skills"])
write("t_vision/App/App.swift", "import RealityKit\nImmersiveSpace(id: \"room\") { }\n")
case("visionOS repo", [TGT, ROOT / "t_vision"], 0, ["visionOS"])
write("t_mixed/web/index.html", "<a-scene></a-scene>")
write("t_mixed/godot/project.godot", "[xr]\nopenxr/enabled=true\n")
case("two platforms -> both listed, asks", [TGT, ROOT / "t_mixed"], 0, ["A-Frame", "Godot OpenXR", "ask which one"])
write("t_none/src/app.js", "console.log(1)")
case("no XR signal -> not verified", [TGT, ROOT / "t_none"], 2, ["no XR signal"])
case("not a folder -> blocked", [TGT, ROOT / "nope"], 2, ["blocked"])

print("#### webar-preview")
AR = skill("webar-preview", "ar_preview.py")
case("cube declared at its real size -> pass", [AR, "scale", M["cube.glb"], "--size", "1x2x3"], 0, ["RESULT pass"])
case("declared 100 times smaller -> fail, names centimetres", [AR, "scale", M["cube.glb"], "--height", "0.02"], 1, ["probably made in centimetres"])
case("longest side check", [AR, "scale", M["cube.glb"], "--longest", "3"], 0, ["longest side"])
case("no size declared -> blocked", [AR, "scale", M["cube.glb"]], 2, ["never assumed"])
case("error page as model -> fail", [AR, "scale", M["error_page.glb"], "--height", "1"], 1, ["RESULT fail"])
case("floating base is pointed out", [AR, "scale", M["two_boxes.glb"], "--longest", "6"], 0, ["base is not at y = 0"])
usd = ROOT / "usd"
usd.mkdir()
USDA = '#usda 1.0\n(\n    defaultPrim = "Cube"\n    metersPerUnit = {mpu}\n    upAxis = "Y"\n)\n\ndef Xform "Cube"\n{{\n    double3 xformOp:translate = (0, 1, 0)\n    float3 xformOp:scale = ({sx}, {sy}, {sz})\n    uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"]\n\n    def Mesh "Box"\n    {{\n        float3[] extent = [(-0.5, -0.5, -0.5), (0.5, 0.5, 0.5)]\n        int[] faceVertexCounts = [3]\n        int[] faceVertexIndices = [0, 1, 2]\n        point3f[] points = [(-0.5, -0.5, -0.5), (0.5, 0.5, 0.5), (0.5, -0.5, -0.5)]\n    }}\n}}\n'


def usdz(name, mpu=1, scale=(1, 2, 3), compress=False):
    layer = usd / f"{name}.usda"
    layer.write_text(USDA.format(mpu=mpu, sx=scale[0], sy=scale[1], sz=scale[2]))
    target = usd / f"{name}.usdz"
    if shutil.which("usdzip") and not compress:
        subprocess.run(["usdzip", str(target), str(layer)], capture_output=True, cwd=usd)
    else:
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED) as z:
            z.write(layer, layer.name)
    return target


have_usd = bool(shutil.which("usdcat") and shutil.which("usdchecker"))
print(f"note: usdcat and usdchecker {'present: real Apple USD tools are used' if have_usd else 'absent: the text layer is read directly'}")
good = usdz("twin")
case("USDZ twin agrees with the GLB and the real size", [AR, "usdz", good, "--glb", M["cube.glb"], "--size", "1x2x3"], 0,
     ["bounding box 1.0000 x 2.0000 x 3.0000 m", "twin largest side"] + (["usdchecker --arkit: Success"] if have_usd else []))
cm = usdz("cm", mpu=0.01)
case("USDZ in centimetres without rescale -> fail", [AR, "usdz", cm, "--glb", M["cube.glb"]], 1, ["0.01 times the GLB's"])
case("compressed USDZ -> fail", [AR, "usdz", usdz("packed", compress=True)], 1, ["files are compressed"])
case("not a USDZ -> fail", [AR, "usdz", M["error_page.glb"]], 1, ["not a USDZ archive"])
case("missing USDZ -> not verified", [AR, "usdz", usd / "none.usdz"], 2, ["no such file"])
converter = next((n for n in ("usdzconvert", "usd_from_gltf") if shutil.which(n)), None)
if converter:
    print(f"note: a converter ({converter}) is installed; the blocked case is skipped")
else:
    case("convert without a converter -> blocked", [AR, "convert", M["cube.glb"], "--out", usd / "made.usdz"], 2, ["blocked: no GLB to USDZ converter"])
viewer = write("vendor/model-viewer.min.js", "// stand-in file for the test; the real viewer is not shipped or downloaded\n")
case("page with viewer and USDZ -> pass", [AR, "page", "--glb", M["cube.glb"], "--usdz", good, "--viewer-script", viewer, "--out", ROOT / "site", "--size", "1x2x3", "--title", "Test cube"], 0,
     ["a model-viewer element and a Quick Look link", "not proven by this script", "RESULT pass"])
page = (ROOT / "site" / "index.html").read_text()
expect("page has the model-viewer element with ar-scale fixed, ios-src and a rel=ar link",
       '<model-viewer src="cube.glb" ios-src="twin.usdz"' in page and 'ar-scale="fixed"' in page and 'rel="ar" href="twin.usdz"' in page)
expect("model files copied beside the page", (ROOT / "site" / "cube.glb").is_file() and (ROOT / "site" / "twin.usdz").is_file())
case("page folder exists -> blocked", [AR, "page", "--glb", M["cube.glb"], "--usdz", good, "--out", ROOT / "site", "--size", "1x2x3"], 2, ["already exists"])
case("page with a wrong declared size -> fail, no page", [AR, "page", "--glb", M["cube.glb"], "--usdz", good, "--out", ROOT / "site2", "--height", "0.5"], 1, ["RESULT fail"])
expect("no page was written after the failed size check", not (ROOT / "site2").exists())
case("page with no way into AR -> blocked", [AR, "page", "--glb", M["cube.glb"], "--out", ROOT / "site3", "--size", "1x2x3"], 2, ["nothing on the page could open AR"])

failed = results.count(False)
print(f"\n{len(results)} checks, {failed} failed")
sys.exit(1 if failed else 0)

"""Test app-size's script on bundles and archives this test builds with known file sizes.

Usage: python3 app_size_cases.py <new folder under .testrun/>

Every expected number is computed from the sizes the test wrote. One case measures a real
macOS app (the system Calculator, read-only) and compares the total with the sum that
`find` and `stat` give. No real iOS build and no real .ipa from Xcode was measured.
"""
import json
import os
import pathlib
import plistlib
import subprocess
import sys
import zipfile

import fixtures as fx

W = fx.workdir(sys.argv)
SCRIPT = fx.SKILLS / "app-size" / "scripts" / "appsize.py"
PY = sys.executable
c = fx.Cases("app-size")
proj = W / "project"
proj.mkdir()

V1 = {"Notes": 400_000, "Assets.car": 250_000, "Info.plist": None, "PkgInfo": 8, "Frameworks/Sync.framework/Sync": 300_000,
      "Frameworks/Sync.framework/Info.plist": 700, "en.lproj/Localizable.strings": 2_000, "de.lproj/Localizable.strings": 2_500,
      "Sounds/chime.caf": 40_000}
V2 = dict(V1)
V2.update({"Notes": 460_000, "Assets.car": 900_000, "Frameworks/Sync.framework/Sync": 290_000, "Onboarding/video.mp4": 1_500_000})
del V2["Sounds/chime.caf"]


def build(folder, spec, mac=False):
    app = folder / "Notes.app"
    base = app / "Contents" if mac else app
    sizes = {}
    for rel, size in spec.items():
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if rel == "Info.plist":
            with path.open("wb") as handle:
                plistlib.dump({"CFBundleExecutable": "Notes", "CFBundleIdentifier": "in.acme.notes"}, handle)
        else:
            path.write_bytes(os.urandom(size))
        sizes[("Contents/" if mac else "") + rel] = path.stat().st_size
    return app, sizes


def ipa(app, name):
    out = app.parent / name
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(app.rglob("*")):
            if path.is_file() and not path.is_symlink():
                z.write(path, "Payload/Notes.app/" + str(path.relative_to(app)))
    return out


(W / "v1").mkdir()
(W / "v2").mkdir()
app1, sizes1 = build(W / "v1", V1)
app2, sizes2 = build(W / "v2", V2)
os.symlink("Notes", app1 / "NotesLink")
total1, total2 = sum(sizes1.values()), sum(sizes2.values())
run = lambda want, label, args, **kw: c.run(want, label, [PY, SCRIPT] + [str(a) for a in args], cwd=proj, **kw)

run(0, "measure: an app bundle", ["measure", app1])
c.has(f"total: {total1} bytes")
c.has(f"in {len(sizes1)} files; 1 symbolic links counted as 0")
c.has("Notes (executable)")
c.has(f"{sizes1['Frameworks/Sync.framework/Sync'] + sizes1['Frameworks/Sync.framework/Info.plist']:>13}", "the Frameworks part is the sum of its two files")
c.has("*.lproj (translations)")
c.has("not saved")
c.true(not (proj / ".mstack").exists(), "measure without --save writes nothing")
run(2, "compare with no baseline is not verified", ["compare", app1])
c.last_line("RESULT not verified: no baseline")
run(0, "measure --save writes the baseline", ["measure", app1, "--save"])
base = proj / ".mstack" / "app-size" / "Notes.json"
c.true(json.loads(base.read_text())["total"] == total1, "baseline file holds the total")
run(2, "measure --save again refuses to replace it", ["measure", app2, "--save"])
c.last_line("blocked:")
c.true(json.loads(base.read_text())["total"] == total1, "the baseline is unchanged after the refusal")
run(0, "compare: the same build shows no change", ["compare", app1])
c.has("change: +0 bytes")
run(0, "compare: a later build, no limit, is a report", ["compare", app2])
c.has(f"change: {total2 - total1:+} bytes")
c.has("no limit was given")
c.has(f"{sizes2['Assets.car'] - sizes1['Assets.car']:>+13}  Assets.car", "Assets.car growth is listed")
c.has(f"{1_500_000:>+13}  Onboarding/video.mp4", "the new file is listed")
c.has(f"{-40_000:>+13}  Sounds/chime.caf", "the removed file is listed")
c.has(f"{-10_000:>+13}  Frameworks/Sync.framework/Sync", "the file that shrank is listed")
c.has("files that grew: 2")
c.has("new files: 1")
c.has("removed files: 1")
run(1, "compare: above the user's total limit fails", ["compare", app2, "--max-bytes", total2 - 1])
c.last_line("RESULT fail: total")
run(0, "compare: exactly at the user's total limit passes", ["compare", app2, "--max-bytes", total2])
run(1, "compare: growth above the user's percent limit fails", ["compare", app2, "--max-growth-percent", "10"])
run(0, "compare: growth within a generous percent limit passes", ["compare", app2, "--max-growth-percent", "500"])
c.has("within the 1 limit(s) given")
run(1, "compare: growth above the user's byte limit fails", ["compare", app2, "--max-growth-bytes", "1000"])
run(0, "compare: a build that shrank passes a zero-growth limit", ["compare", app1, "--max-growth-bytes", "0"])
run(0, "measure --replace keeps the old baseline under a dated name", ["measure", app2, "--replace"])
kept = [p for p in base.parent.glob("Notes.*.json")]
c.true(len(kept) == 1 and json.loads(kept[0].read_text())["total"] == total1 and json.loads(base.read_text())["total"] == total2,
       "old baseline kept, new baseline in place")

ipa1, ipa2 = ipa(app1, "Notes.ipa"), ipa(app2, "Notes.ipa")
run(0, "ipa: measure and save under another name", ["measure", ipa1, "--save", "--name", "notes-ipa"])
c.has(f"total: {total1} bytes")
c.has("zip's own compression, not the store's")
run(0, "ipa: compare a later archive", ["compare", ipa2, "--name", "notes-ipa"])
c.has(f"change: {total2 - total1:+} bytes")
mac_app, mac_sizes = build(W / "mac", {"Info.plist": None, "MacOS/Notes": 500_000, "Resources/icon.icns": 90_000, "Frameworks/A.dylib": 70_000}, mac=True)
run(0, "macOS bundle: parts are the folders under Contents", ["measure", mac_app])
c.has("Contents/MacOS")
c.has("Contents/Resources")
c.has("macOS app bundle")

(W / "Empty.app").mkdir()
run(1, "an empty bundle fails", ["measure", W / "Empty.app"])
run(2, "a missing path is blocked", ["measure", W / "Nope.app"])
(W / "folder").mkdir()
run(2, "a folder that is not an .app is blocked", ["measure", W / "folder"])
(W / "bad.ipa").write_bytes(b"not a zip")
run(2, "an .ipa that is not a zip is not verified", ["measure", W / "bad.ipa"])
with zipfile.ZipFile(W / "noapp.zip", "w") as z:
    z.writestr("readme.txt", "hello")
run(2, "a zip with no .app inside is not verified", ["measure", W / "noapp.zip"])
(W / "build.tar").write_bytes(b"x")
run(2, "another file type is blocked", ["measure", W / "build.tar"])
base.write_text("{broken")
run(2, "a damaged baseline is not verified", ["compare", app2])

calc = pathlib.Path("/System/Applications/Calculator.app")
if sys.platform == "darwin" and calc.is_dir():
    found = subprocess.run(["find", str(calc), "-type", "f", "-exec", "stat", "-f", "%z", "{}", "+"], capture_output=True, text=True)
    expect = sum(int(x) for x in found.stdout.split())
    run(0, "real macOS app: measured read-only", ["measure", calc])
    c.has(f"total: {expect} bytes", f"total equals the sum from find and stat ({expect} bytes)")
else:
    print("not run: no system Calculator to measure")
c.run(0, "--help works", [PY, SCRIPT, "--help"])
sys.exit(c.finish())

"""Test mac-release-verify's script with the real codesign, spctl and stapler of the macOS machine it runs on.

Usage: python3 mac_release_verify_cases.py <new folder under .testrun/>

Read-only: nothing is signed, notarised, installed or changed. The cases use
  - an unsigned bundle and an unsigned disk image this test builds in the work folder,
  - /System/Applications/Calculator.app (signed by the system, no stapled ticket),
  - when present, apps in /Applications that Gatekeeper reports as notarised (found by asking
    spctl and stapler; one with a stapled ticket, one without).
The disk image cases attach the image read-only and detach it again.
Not macOS: every case is skipped except the blocked one.
"""
import os
import pathlib
import plistlib
import shutil
import subprocess
import sys

import fixtures as fx

W = fx.workdir(sys.argv)
SCRIPT = fx.SKILLS / "mac-release-verify" / "scripts" / "macverify.py"
PY = sys.executable
c = fx.Cases("mac-release-verify")

if sys.platform != "darwin":
    c.run(2, "not macOS: blocked", [PY, SCRIPT, W])
    print("not run: every other case needs macOS")
    sys.exit(c.finish())


def make_app(folder, name="Plain", version="1.2.0", plist=True):
    app = folder / f"{name}.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    exe = app / "Contents" / "MacOS" / name
    exe.write_text("#!/bin/sh\necho hello\n")
    exe.chmod(0o755)
    if plist:
        with (app / "Contents" / "Info.plist").open("wb") as handle:
            plistlib.dump({"CFBundleExecutable": name, "CFBundleIdentifier": f"com.example.{name.lower()}",
                           "CFBundlePackageType": "APPL", "CFBundleShortVersionString": version, "CFBundleVersion": "7"}, handle)
    return app


proj = W / "project"
proj.mkdir()
plain = make_app(W)

c.run(1, "unsigned bundle: fails", [PY, SCRIPT, plain], cwd=proj)
c.has("not signed at all")
c.has("0 pass, 3 fail, 0 could not check")
c.last_line("RESULT fail")
saved = sorted((proj / ".mstack" / "mac-release-verify").glob("*/report.json"))
c.true(len(saved) == 1 and (saved[0].parent / "signature.txt").read_text().startswith("$ "), "raw tool output and report.json kept under .mstack/mac-release-verify")
c.run(1, "version that does not match is one more failure", [PY, SCRIPT, plain, "--expect-version", "1.3.0", "--no-save"], cwd=proj)
c.has("Info.plist says 1.2.0, expected 1.3.0")
c.run(1, "version that matches is a pass line, the rest still fails", [PY, SCRIPT, plain, "--expect-version", "1.2.0", "--no-save"], cwd=proj)
c.has("1 pass, 3 fail")
broken = make_app(W / "b", plist=False)
c.run(1, "bundle with no Info.plist fails", [PY, SCRIPT, broken, "--no-save"], cwd=proj)

c.run(2, "path that does not exist: blocked", [PY, SCRIPT, W / "Nope.app"], cwd=proj)
c.last_line("blocked:")
(W / "file.app").write_text("not a bundle")
c.run(2, "a plain file named .app: blocked", [PY, SCRIPT, W / "file.app"], cwd=proj)
(W / "build.zip").write_bytes(b"PK")
c.run(2, "a .zip: blocked", [PY, SCRIPT, W / "build.zip"], cwd=proj)
c.run(2, "no tools on PATH: every check is 'could not check'", [sys.executable, SCRIPT, plain, "--no-save"], cwd=proj, env=dict(os.environ, PATH="/var/empty"))
c.has("0 pass, 0 fail, 3 could not check")
c.last_line("RESULT not verified")

calc = pathlib.Path("/System/Applications/Calculator.app")
if calc.is_dir():
    c.run(1, "system Calculator: signature and Gatekeeper pass, no stapled ticket", [PY, SCRIPT, calc, "--no-save"], cwd=proj)
    c.has("2 pass, 1 fail")
    c.has("no notarisation ticket is stapled")
else:
    print("not run: no system Calculator on this Mac")

stapled = unstapled = None
for app in sorted(pathlib.Path("/Applications").glob("*.app")):
    seen = subprocess.run(["spctl", "--assess", "--type", "execute", "--verbose=4", str(app)], capture_output=True, text=True)
    if "Notarized Developer ID" not in seen.stdout + seen.stderr:
        continue
    ticket = subprocess.run(["xcrun", "stapler", "validate", str(app)], capture_output=True, text=True)
    if ticket.returncode == 0 and stapled is None:
        stapled = app
    elif ticket.returncode != 0 and unstapled is None:
        unstapled = app
    if stapled and unstapled:
        break
if stapled:
    c.run(0, "a notarised app with a stapled ticket passes all three checks", [PY, SCRIPT, stapled, "--no-save"], cwd=proj)
    c.has("3 pass, 0 fail, 0 could not check")
    c.has("source: Notarized Developer ID")
    c.run(1, "the same app with a wrong expected team fails on the team line", [PY, SCRIPT, stapled, "--expect-team", "ZZZZZZZZZZ", "--no-save"], cwd=proj)
else:
    print("not run: no notarised app with a stapled ticket was found in /Applications, so no real pass was seen")
if unstapled:
    c.run(1, "a notarised app without a stapled ticket fails only on the staple", [PY, SCRIPT, unstapled, "--no-save"], cwd=proj)
    c.has("2 pass, 1 fail")
else:
    print("not run: no notarised app lacking a staple was found in /Applications")

if shutil.which("hdiutil"):
    src = W / "dmg-src"
    src.mkdir()
    make_app(src)
    dmg = W / "Plain.dmg"
    made = subprocess.run(["hdiutil", "create", "-quiet", "-srcfolder", str(src), "-volname", "PlainTest", "-format", "UDZO", str(dmg)], capture_output=True, text=True)
    if made.returncode == 0 and dmg.exists():
        c.run(1, "unsigned disk image fails", [PY, SCRIPT, dmg, "--no-save"], cwd=proj)
        c.has("app inside")
        c.run(1, "unsigned disk image with --mount: the app inside is checked and fails too", [PY, SCRIPT, dmg, "--mount", "--no-save"], cwd=proj)
        c.has("inner signature")
        c.has("Plain.app (image attached read-only")
        attached = subprocess.run(["hdiutil", "info"], capture_output=True, text=True).stdout
        c.true("mstack-macverify-" not in attached, "the image is detached again after the check")
    else:
        print(f"not run: hdiutil could not build a test image ({made.stderr.strip()[:120]})")
else:
    print("not run: hdiutil is not on this machine")
c.run(0, "--help works", [PY, SCRIPT, "--help"])
sys.exit(c.finish())

"""Test ios-submit-check's script on small iPhone-project-shaped folders this test writes.

Usage: python3 ios_submit_check_cases.py <new folder under .testrun/>

The projects are hand-written (an Info.plist, a privacy manifest, an icon set, Swift files),
not made by Xcode. The rule tables are unverified, so these cases prove the script applies
its tables, not that the tables match Apple's current rules.
"""
import json
import plistlib
import shutil
import sys

import fixtures as fx

W = fx.workdir(sys.argv)
SCRIPT = fx.SKILLS / "ios-submit-check" / "scripts" / "submitcheck.py"
PY = sys.executable
c = fx.Cases("ios-submit-check")
INFO = {"CFBundleIdentifier": "in.acme.notes", "CFBundleShortVersionString": "1.2.0", "CFBundleVersion": "14",
        "NSCameraUsageDescription": "Notes uses the camera to scan paper pages into a note.", "ITSAppUsesNonExemptEncryption": False}
MANIFEST = {"NSPrivacyAccessedAPITypes": [{"NSPrivacyAccessedAPIType": "NSPrivacyAccessedAPICategoryUserDefaults", "NSPrivacyAccessedAPITypeReasons": ["CA92.1"]}]}
SWIFT = "import AVFoundation\nlet session = AVCaptureDevice.default(for: .video)\nlet d = UserDefaults.standard\n"
n = 0


def project(info=INFO, manifest=MANIFEST, swift=SWIFT, icon="opaque", extension=None):
    global n
    n += 1
    root = W / f"p{n:02d}"
    app = root / "Notes"
    app.mkdir(parents=True)
    with (app / "Info.plist").open("wb") as h:
        plistlib.dump(info, h)
    if manifest is not None:
        with (app / "PrivacyInfo.xcprivacy").open("wb") as h:
            plistlib.dump(manifest, h)
    (app / "Scanner.swift").write_text(swift)
    if icon:
        s = app / "Assets.xcassets" / "AppIcon.appiconset"
        s.mkdir(parents=True)
        (s / "Contents.json").write_text(json.dumps({"images": [{"filename": "icon.png", "idiom": "universal", "platform": "ios", "size": "1024x1024"}]}))
        if icon == "opaque":
            fx.write_png(s / "icon.png", fx.picture(1024, 1024))
        elif icon == "alpha":
            fx.write_png(s / "icon.png", fx.picture(1024, 1024, alpha=255), colour_type=6)
        elif icon == "small":
            fx.write_png(s / "icon.png", fx.picture(512, 512))
    if extension:
        ext = root / "Widget"
        ext.mkdir()
        with (ext / "Info.plist").open("wb") as h:
            plistlib.dump(extension, h)
    return root


def check(want, label, root, *texts, extra=()):
    c.run(want, label, [PY, SCRIPT, "--project", root, *extra])
    for t in texts:
        c.has(t)


check(0, "a sound project passes", project(), "unverified, written from memory", "0 warnings")
c.last_line("RESULT pass")
check(1, "camera used, no purpose string", project(info={k: v for k, v in INFO.items() if k != "NSCameraUsageDescription"}), "source uses AVCaptureDevice")
check(1, "placeholder purpose string", project(info=dict(INFO, NSCameraUsageDescription="TODO")), "empty or a placeholder")
check(1, "no privacy manifest", project(manifest=None), "no PrivacyInfo.xcprivacy")
check(1, "UserDefaults used but not declared", project(manifest={"NSPrivacyAccessedAPITypes": []}), "does not declare NSPrivacyAccessedAPICategoryUserDefaults")
check(1, "category declared with no reason", project(manifest={"NSPrivacyAccessedAPITypes": [{"NSPrivacyAccessedAPIType": "NSPrivacyAccessedAPICategoryUserDefaults", "NSPrivacyAccessedAPITypeReasons": []}]}), "declared with no reason")
check(1, "bad version string", project(info=dict(INFO, CFBundleShortVersionString="1.2 beta")), "is not one to three dot-separated numbers")
check(1, "no build number", project(info={k: v for k, v in INFO.items() if k != "CFBundleVersion"}), "no CFBundleVersion")
check(1, "extension with another version", project(extension={"CFBundleShortVersionString": "1.1.0", "CFBundleVersion": "14"}), "differs across targets")
check(1, "icon with alpha", project(icon="alpha"), "has an alpha channel")
check(1, "icon of the wrong size", project(icon="small"), "is 512x512")
check(1, "no icon set", project(icon=None), "no AppIcon.appiconset")
check(0, "no export-compliance key is a warning only", project(info={k: v for k, v in INFO.items() if k != "ITSAppUsesNonExemptEncryption"}), "ITSAppUsesNonExemptEncryption is not set")
check(0, "$(MARKETING_VERSION) resolved from project.pbxproj", None or (lambda r: ((r / "Notes.xcodeproj").mkdir(), (r / "Notes.xcodeproj" / "project.pbxproj").write_text("\t\tMARKETING_VERSION = 1.2.0;\n\t\tCURRENT_PROJECT_VERSION = 14;\n"), r)[2])(
      project(info=dict(INFO, CFBundleShortVersionString="$(MARKETING_VERSION)", CFBundleVersion="$(CURRENT_PROJECT_VERSION)"))), "CFBundleShortVersionString = 1.2.0")
shots = W / "shots"
fx.write_png(shots / "home.png", fx.picture(1290, 2796))
check(0, "a screenshot of a listed size passes", project(), "iPhone 6.9 inch (size table unverified)", extra=("--screenshots", shots))
fx.write_png(shots / "odd.png", fx.picture(1000, 2000))
fx.write_png(shots / "blank.png", fx.flat(1290, 2796))
check(1, "odd size and blank screenshot both fail", W / "p01", "1000x2000 is not a size in the table", "blank.png: blank", extra=("--screenshots", shots))
empty = W / "empty"
empty.mkdir()
check(2, "a folder with no Info.plist is blocked", empty, "blocked: no Info.plist")
check(2, "a missing folder is blocked", W / "nope")
c.run(0, "--help works", [PY, SCRIPT, "--help"])
sys.exit(c.finish())

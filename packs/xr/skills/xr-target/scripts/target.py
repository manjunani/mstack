#!/usr/bin/env python3
"""Find out which XR platform and stack a repository targets, from evidence in its files.

  target.py [project folder] [--json]

Looks for these signals and prints each one with the file and line that shows it:
  web     three.js with renderer.xr enabled, A-Frame, Babylon.js WebXR, React Three Fiber XR, Meta IWSDK
  unity   Packages/manifest.json entries for XR packages (OpenXR, XR Interaction Toolkit, Meta, PolySpatial)
  android AndroidManifest.xml entries for VR (Quest) and AR (ARCore)
  apple   visionOS targets and RealityKit or ARKit imports in Xcode projects and Swift files
  unreal  .uproject files with XR plugins
  godot   project.godot with OpenXR enabled

Prints one target record: platform, stack, versions where a manifest states them, and the evidence. When
signals point to more than one stack it lists them all and says so; it never picks silently.
For a Meta Quest target it says to use Meta's own skills when they are installed.

Exit codes: 0 = a target was found, 2 = no XR signal (not verified) or not a folder (blocked).
This script only reads files.
"""
import argparse
import json
import pathlib
import re
import sys

SKIP = {"node_modules", ".git", "dist", "build", "Library", "Temp", "obj", "out", ".mstack", ".testrun", "Pods", "DerivedData", ".gradle"}
TEXT = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".html", ".vue", ".svelte", ".swift", ".json", ".xml", ".gradle", ".kts",
        ".pbxproj", ".uproject", ".godot", ".cs", ".toml"}
SIGNALS = [
    ("web", "three.js WebXR", re.compile(r"\.xr\.enabled\s*=\s*true|VRButton|ARButton|XRButton")),
    ("web", "React Three Fiber XR", re.compile(r"@react-three/xr")),
    ("web", "A-Frame", re.compile(r"<a-scene|['\"]aframe['\"]")),
    ("web", "Babylon.js WebXR", re.compile(r"createDefaultXRExperienceAsync|WebXRExperienceHelper|@babylonjs/core")),
    ("web", "Meta IWSDK", re.compile(r"@iwsdk/")),
    ("web", "plain WebXR API", re.compile(r"navigator\.xr\.requestSession")),
    ("unity", "Unity OpenXR", re.compile(r"\"com\.unity\.xr\.openxr\"")),
    ("unity", "Unity XR Interaction Toolkit", re.compile(r"\"com\.unity\.xr\.interaction\.toolkit\"")),
    ("unity", "Unity Meta XR SDK", re.compile(r"\"com\.meta\.xr\.[\w.]+\"|\"com\.oculus\.[\w.]+\"")),
    ("unity", "Unity visionOS (PolySpatial)", re.compile(r"\"com\.unity\.polyspatial[\w.]*\"|\"com\.unity\.xr\.visionos\"")),
    ("android", "Android VR headset (Quest)", re.compile(r"com\.oculus\.intent\.category\.VR|com\.oculus\.supportedDevices|android\.hardware\.vr\.headtracking")),
    ("android", "Android ARCore", re.compile(r"com\.google\.ar\.core")),
    ("apple", "visionOS", re.compile(r"\bxros\b|XROS_DEPLOYMENT_TARGET|SUPPORTED_PLATFORMS\s*=\s*\"?[^\n]*xros|\bimport\s+RealityKit\b.*|ImmersiveSpace")),
    ("apple", "ARKit (iOS)", re.compile(r"\bimport\s+ARKit\b|ARWorldTrackingConfiguration")),
    ("unreal", "Unreal OpenXR", re.compile(r"\"Name\"\s*:\s*\"(OpenXR|OculusXR|MetaXR)\w*\"")),
    ("godot", "Godot OpenXR", re.compile(r"openxr/enabled\s*=\s*true")),
]
QUEST = {"Android VR headset (Quest)", "Unity Meta XR SDK", "Meta IWSDK"}
VERSION = re.compile(r"\"(three|aframe|@react-three/xr|@babylonjs/core|com\.unity\.xr\.openxr|com\.meta\.xr\.sdk\.core)\"\s*:\s*\"([^\"]+)\"")


def walk(root):
    stack = [root]
    while stack:
        folder = stack.pop()
        try:
            entries = sorted(folder.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name not in SKIP and not entry.name.startswith("."):
                    stack.append(entry)
            elif (entry.suffix in TEXT or entry.name in ("project.godot",)) and entry.stat().st_size < 2_000_000:
                yield entry


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", nargs="?", default=".", type=pathlib.Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    root = args.project
    if not root.is_dir():
        print(f"blocked: {root} is not a folder")
        return 2
    evidence, versions = {}, {}
    for path in walk(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), 1):
            for platform, stack, pattern in SIGNALS:
                if pattern.search(line):
                    evidence.setdefault((platform, stack), [])
                    if len(evidence[(platform, stack)]) < 3:
                        evidence[(platform, stack)].append(f"{path.relative_to(root)}:{number}: {line.strip()[:100]}")
            if path.name in ("package.json", "manifest.json"):
                for name, version in VERSION.findall(line):
                    versions[name] = version
    if ("web", "plain WebXR API") in evidence and len([k for k in evidence if k[0] == "web"]) > 1:
        evidence.pop(("web", "plain WebXR API"))
    stacks = sorted(evidence)
    quest = any(stack in QUEST for _, stack in stacks)
    record = {"platforms": sorted({p for p, _ in stacks}), "stacks": [s for _, s in stacks], "versions": versions,
              "meta_quest": quest, "evidence": {s: lines for (_, s), lines in evidence.items()}}
    if args.json:
        print(json.dumps(record, indent=2))
    else:
        for (platform, stack), lines in sorted(evidence.items()):
            print(f"{platform:<8} {stack}")
            for line in lines:
                print(f"         {line}")
        for name, version in sorted(versions.items()):
            print(f"version  {name} {version}")
    if not stacks:
        print("RESULT not verified: no XR signal found in this repository; it may not target XR yet, or uses a stack this script does not know")
        return 2
    if len(record["platforms"]) > 1:
        print(f"note: signals for {len(record['platforms'])} platforms ({', '.join(record['platforms'])}); ask which one this task is about")
    if quest:
        print("next: this targets Meta Quest. Use Meta's own skills for platform questions if they are installed (the meta-vr plugin); "
              "if not, check claims against Meta's current developer documentation")
    if "web" in record["platforms"]:
        print("next: for a WebXR page use webxr-verify; for UI distances and text sizes use xr-comfort-review")
    print("RESULT pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())

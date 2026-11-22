#!/usr/bin/env python3
"""Scan a web project's source for what a WebXR session needs, before any browser is opened.

  xr_scan.py [project folder] [--mode vr|ar|any]

It looks for, and prints the evidence line for each:
  session request   navigator.xr.requestSession('immersive-vr' or 'immersive-ar'), a VR/AR/XR button helper,
                    or a framework that requests the session for you (A-Frame, @react-three/xr, IWSDK)
  support check     navigator.xr.isSessionSupported(...), so the page can say "no XR here" instead of breaking
  render loop       renderer.setAnimationLoop / session.requestAnimationFrame (window.requestAnimationFrame stops in XR)
  xr enabled        renderer.xr.enabled = true (three.js), or a framework that does it
  controllers       select events, inputSources, gamepad, renderer.xr.getController
  hands             'hand-tracking' feature, inputSource.hand, renderer.xr.getHand, XRHand
  exit path         session.end() or an 'end' listener that restores the page
  secure context    WebXR only works on https or localhost; dev server config is checked for https

A missing session request or render loop is a fail. Missing support check, input or exit path are
warnings: the page can work, but some users will be stuck. The scan proves nothing about what renders.
Exit codes: 0 = pass, 1 = fail, 2 = blocked (not a folder, no source files).
"""
import argparse
import pathlib
import re
import sys

SKIP = {"node_modules", ".git", "dist", "build", "out", ".next", "coverage", ".mstack", ".testrun", "vendor"}
SOURCE = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte", ".html", ".astro"}
FRAMEWORK = re.compile(r"<a-scene|aframe|@react-three/xr|createXRStore|@iwsdk/|XRButton|VRButton|ARButton")
CHECKS = {
    "session_vr": re.compile(r"requestSession\s*\(\s*['\"`]immersive-vr|VRButton|<a-scene|enterVR\b|enterVR\s*\(|vr-mode-ui"),
    "session_ar": re.compile(r"requestSession\s*\(\s*['\"`]immersive-ar|ARButton|enterAR\b|ar-mode-ui"),
    "session_any": re.compile(r"requestSession\s*\(|XRButton|VRButton|ARButton|<a-scene|createXRStore|enterVR|enterAR|@iwsdk/"),
    "support": re.compile(r"isSessionSupported\s*\(|XRButton|VRButton|ARButton|<a-scene|createXRStore|@iwsdk/"),
    "loop": re.compile(r"setAnimationLoop\s*\(|session\.requestAnimationFrame|xrSession\.requestAnimationFrame|useFrame\s*\(|<a-scene|@iwsdk/"),
    "xr_enabled": re.compile(r"\.xr\.enabled\s*=\s*true|<a-scene|createXRStore|<XR\b|@iwsdk/"),
    "controllers": re.compile(r"getController\s*\(|inputSources|['\"]select(start|end)?['\"]|\.gamepad\b|laser-controls|tracked-controls|useXRInputSourceState|oculus-touch-controls"),
    "hands": re.compile(r"['\"]hand-tracking['\"]|\.hand\b|getHand\s*\(|XRHand|hand-tracking-controls|handTracking"),
    "exit": re.compile(r"\.end\s*\(\s*\)|addEventListener\s*\(\s*['\"]end['\"]|onend\s*=|exitVR|exit-vr|sessionend|XRButton|VRButton|ARButton|createXRStore"),
}
HTTPS_HINT = re.compile(r"https\s*:\s*(true|\{)|basicSsl|mkcert|--https|server\.https|HTTPS=true")


def files(root):
    stack = [root]
    while stack:
        folder = stack.pop()
        for entry in sorted(folder.iterdir()):
            if entry.is_dir():
                if entry.name not in SKIP and not entry.name.startswith("."):
                    stack.append(entry)
            elif entry.suffix in SOURCE and entry.stat().st_size < 1_000_000:
                yield entry


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", nargs="?", default=".", type=pathlib.Path)
    parser.add_argument("--mode", choices=["vr", "ar", "any"], default="any", help="which immersive mode the page has to offer")
    args = parser.parse_args()
    root = args.project
    if not root.is_dir():
        print(f"blocked: {root} is not a folder")
        return 2
    found = {key: [] for key in CHECKS}
    framework, count = [], 0
    for path in files(root):
        count += 1
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for number, line in enumerate(lines, 1):
            where = f"{path.relative_to(root)}:{number}: {line.strip()[:110]}"
            for key, pattern in CHECKS.items():
                if pattern.search(line) and len(found[key]) < 3:
                    found[key].append(where)
            if FRAMEWORK.search(line) and len(framework) < 3:
                framework.append(where)
    if count == 0:
        print(f"blocked: no web source files under {root}")
        return 2
    https = []
    for name in ("vite.config.js", "vite.config.ts", "vite.config.mjs", "package.json", "webpack.config.js", ".env"):
        path = root / name
        if path.is_file() and HTTPS_HINT.search(path.read_text(encoding="utf-8", errors="replace")):
            https.append(name)
    session_key = {"vr": "session_vr", "ar": "session_ar", "any": "session_any"}[args.mode]
    rows = [
        ("session request" + ("" if args.mode == "any" else f" ({args.mode})"), session_key, "fail"),
        ("render loop that runs in XR", "loop", "fail"),
        ("XR enabled on the renderer", "xr_enabled", "warn"),
        ("support check", "support", "warn"),
        ("controller input", "controllers", "warn"),
        ("hand input", "hands", "warn"),
        ("exit path", "exit", "warn"),
    ]
    failures, warnings = [], []
    print(f"scanned {count} source files in {root}")
    if framework:
        print(f"framework that manages the session: {framework[0]}")
    for label, key, severity in rows:
        if found[key]:
            print(f"  ok    {label}: {found[key][0]}")
        else:
            print(f"  {'FAIL' if severity == 'fail' else 'warn'}  {label}: not found")
            (failures if severity == "fail" else warnings).append(label)
    print("  note  secure context: WebXR needs https, or http://localhost on the same machine. "
          + (f"https setup seen in {', '.join(https)}." if https else "No https setup found in the dev server config; a headset on the network cannot open an http page."))
    if warnings:
        print("warnings (the page can work, some users will be stuck): " + ", ".join(warnings))
    print("this scan reads text only; it proves nothing about what renders. Next: an emulated session (check_session.py).")
    if failures:
        print("RESULT fail: missing " + ", ".join(failures))
        return 1
    print("RESULT pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())

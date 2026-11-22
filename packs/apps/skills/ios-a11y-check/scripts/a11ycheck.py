#!/usr/bin/env python3
"""Find SwiftUI code that VoiceOver or Dynamic Type users will trip over, and check the largest-text screenshots.

  scan DIR                        read every .swift file under DIR (build folders left out)
  shots DIR [--expect NAME ...]   check the screenshots taken at the largest text size

`scan` reports, with file and line:
  FAIL  icon button      an Image used as a button's label with no accessibilityLabel nearby
  FAIL  fixed font       .font(.system(size: N)) or .custom(_, size: N) with no relativeTo:,
                         or .custom(_, fixedSize:): text that ignores the user's text size
  WARN  image no label   an Image(...) outside a button with no accessibilityLabel and not
                         marked decorative or hidden; decorative images are fine when marked
  WARN  colour only      a colour chosen by a condition (x ? .red : .green) where the lines
                         around it show no text, symbol or label change for the same state
"Nearby" means the same line or the next eight lines. The scan reads text; it does not compile
Swift, so a label set from another file or a helper view is not seen. Each hit means "look".

`shots` checks that each screenshot in DIR is a readable PNG and not blank (the same reader
as sim-proof), and that every --expect name has a file. Taking the screenshots is done on
the simulator at the largest accessibility text size; this script only checks the files.

What only a device or a VoiceOver pass can show, and this script cannot: the order VoiceOver
reads elements, whether a label makes sense spoken aloud, clipped or overlapping text at the
largest size, touch target sizes, and custom actions. The report lists these as not verified.

Exit codes: 0 = no failure (warnings may be listed)
            1 = at least one failure (scan) or a missing or blank screenshot (shots)
            2 = blocked: no Swift files, no screenshot folder
"""
import argparse
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import pngstat  # noqa: E402

SKIP = {"build", "DerivedData", "Pods", ".git", ".build", "Carthage", ".mstack"}
LABELLED = re.compile(r"accessibilityLabel|accessibility\(label|accessibilityHidden\(\s*true|accessibility\(hidden|Image\(decorative|accessibilityElement\(children:\s*\.ignore|Label\(")
IMAGE = re.compile(r"(?<![A-Za-z])Image\((?!decorative)")
FIXED = re.compile(r"\.system\(\s*size:|\.custom\([^)]*size:|Font\.custom\([^)]*size:|\.custom\([^)]*fixedSize:")
COLOUR_COND = re.compile(r"\.(foregroundColor|foregroundStyle|fill|background|tint|stroke)\(\s*[^)]*\?\s*(Color\.|\.)?(red|green|blue|orange|yellow|gray|grey|secondary|primary|accentColor)\b[^)]*:")
NOT_VERIFIED = ["VoiceOver reading order", "whether labels make sense when spoken", "clipped or overlapping text at the largest size",
                "touch target sizes", "custom actions and rotor behaviour"]


def enclosing(lines, i):
    """Index of the line holding the unclosed `{` that encloses line i, or None."""
    depth = 0
    for j in range(i - 1, max(-1, i - 40), -1):
        for ch in reversed(lines[j].split("//")[0]):
            if ch == "}":
                depth += 1
            elif ch == "{":
                if depth == 0:
                    return j
                depth -= 1
    return None


def scan(root):
    files = [p for p in root.rglob("*.swift") if not set(p.relative_to(root).parts) & SKIP]
    fails, warns = [], []
    for path in files:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for i, line in enumerate(lines):
            code = line.split("//")[0]
            window = "\n".join(lines[i:i + 9])
            where = f"{path.relative_to(root)}:{i + 1}"
            if IMAGE.search(code) and not LABELLED.search(window):
                opener = enclosing(lines, i)
                in_button = opener is not None and re.search(r"Button\b|label:", lines[opener])
                text_near = re.search(r"Text\(|Button\(\s*\"", "\n".join(lines[opener if opener is not None else i:i + 3]))
                if in_button and not text_near:
                    fails.append(f"icon button     {where}: {code.strip()[:80]}")
                elif not in_button:
                    warns.append(f"image no label  {where}: {code.strip()[:80]}")
            if FIXED.search(code) and "relativeTo:" not in code:
                fails.append(f"fixed font      {where}: {code.strip()[:80]}")
            if COLOUR_COND.search(code):
                around = "\n".join(lines[max(0, i - 6):i + 7])
                if not re.search(r"Text\([^)]*\?|Image\(systemName:[^)]*\?|accessibilityValue|accessibilityLabel|Label\(", around):
                    warns.append(f"colour only     {where}: {code.strip()[:80]}")
    return files, fails, warns


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("scan", help="scan SwiftUI source")
    p.add_argument("dir")
    p = sub.add_parser("shots", help="check largest-text screenshots")
    p.add_argument("dir")
    p.add_argument("--expect", nargs="*", default=[], help="screen names that must each have a screenshot (file name contains the name)")
    args = parser.parse_args()
    root = pathlib.Path(args.dir)
    if not root.is_dir():
        print(f"blocked: {root} is not a folder")
        return 2

    if args.command == "scan":
        files, fails, warns = scan(root)
        if not files:
            print(f"blocked: no .swift files under {root}")
            return 2
        print(f"scanned: {len(files)} Swift files (text matching; a label set elsewhere is not seen)")
        for line in fails:
            print(f"FAIL  {line}")
        for line in warns:
            print(f"warn  {line}")
        print("not verified by a source scan: " + "; ".join(NOT_VERIFIED) + ". A VoiceOver pass on a device or simulator shows these.")
        if fails:
            print(f"RESULT fail: {len(fails)} failures, {len(warns)} warnings")
            return 1
        print(f"RESULT pass: no failure in {len(files)} files ({len(warns)} warnings to look at)")
        return 0

    try:
        limits, notes = pngstat.load_limits()
    except (OSError, ValueError) as exc:
        print(f"blocked: the thresholds file cannot be used ({exc})")
        return 2
    shots = sorted(root.glob("*.png"))
    if not shots:
        print(f"blocked: no PNG screenshots in {root}. Take them on the simulator at the largest accessibility text size first.")
        return 2
    bad = []
    for shot in shots:
        verdict, line = pngstat.describe(pngstat.stats(shot, limits), limits)
        print(line)
        if verdict != "real":
            bad.append(shot.name)
    missing = [n for n in args.expect if not any(n.lower() in s.name.lower() for s in shots)]
    for name in missing:
        print(f"missing  no screenshot for '{name}'")
    print("not verified from files: whether the text size really was the largest when they were taken, and " + "; ".join(NOT_VERIFIED[2:3]) + ". Look at each picture.")
    if bad or missing:
        print(f"RESULT fail: {len(bad)} blank or broken, {len(missing)} expected screens missing")
        return 1
    print(f"RESULT pass: {len(shots)} screenshots are real pictures" + (f"; all {len(args.expect)} expected screens present" if args.expect else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

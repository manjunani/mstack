#!/usr/bin/env python3
"""Run the diagram-check script on hand-written fixtures.

The fixtures in tests/scripts/fixtures/diagram-check/ are copied to a fresh folder
<base>/design-diagram-check/run-<n>/ (default base: .testrun in the repository root), so the
originals stay untouched and no earlier run is reused. Every case states the exit code it
expects and a piece of text the output has to contain. There is one case per rule, a clean
SVG and a clean compressed draw.io file that pass, Mermaid source, bad input and a missing file.

Usage: diagram_check_cases.py [--base <folder>] [--verbose]
Exit 0 when every case behaves as expected, 1 otherwise.
"""
import argparse
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
PACK = HERE.parent.parent
FIXTURES = HERE / "fixtures" / "diagram-check"
SCRIPT = str(PACK / "skills" / "diagram-check" / "scripts" / "diagram_check.py")


def fresh(base):
    parent = base / "design-diagram-check"
    n = 1
    while (parent / f"run-{n}").exists():
        n += 1
    work = parent / f"run-{n}"
    shutil.copytree(FIXTURES, work)
    return work


CASES = [
    # (label, arguments, expected exit, text the output must contain)
    ("clean SVG passes in light and dark", ["clean.svg"], 0, "RESULT pass: 4 shape(s), 3 label(s), 2 edge(s)"),
    ("two boxes overlap", ["overlap.svg"], 1, "rect#a at (20,40 120x60) and rect#b at (120,60 120x60) overlap by 20x40"),
    ("two labels overlap", ["labels.svg"], 1, 'label text#first "First label" at (30,58.8 84.7x14) and label text#second'),
    ("label runs past its box", ["clipped.svg"], 1, "runs 60.1px past the edge of rect#box at (150,20 80x40)"),
    ("label runs outside the viewBox", ["offcanvas.svg"], 1, "runs 30.9px past the right edge of the canvas"),
    ("small text under 4.5:1 fails, large text at 3.54:1 passes", ["contrast.svg"], 1, "RESULT fail: 1 finding(s): 1 contrast"),
    ("the failing contrast names colours and ratio", ["contrast.svg"], 1, "#888888 on #ffffff is 3.54:1"),
    ("contrast through a CSS descendant selector", ["css.svg"], 1, "#c0c0c0 on #ffffff is 1.82:1"),
    ("shape with no label", ["unlabelled.svg"], 1, "rect#blank at (220,40 120x60) has no text"),
    ("ignored box drops out, so the edge into it is loose", ["unlabelled.svg", "--ignore", "blank"], 1, "RESULT fail: 1 finding(s): 1 loose-edge"),
    ("edge end touches nothing", ["loose.svg"], 1, "edge line#dangling end at (300,150) touches no shape"),
    ("font under the minimum", ["smallfont.svg"], 1, "is 9px; the minimum is 12px"),
    ("font passes at own size, fails when shown smaller", ["clean.svg", "--display-width", "300"], 1, "font sizes scaled by 0.58"),
    ("min font can be lowered", ["smallfont.svg", "--min-font", "9"], 0, "RESULT pass"),
    ("hard-coded caption fails on a dark page", ["theme.svg"], 1, "#1f2937 on #0d1117 is 1.29:1 in the dark theme"),
    ("same file on a light page only passes", ["theme.svg", "--theme", "light"], 0, "RESULT pass"),
    ("prefers-color-scheme rule fixes the theme", ["theme-ok.svg"], 0, "RESULT pass"),
    ("rotated text is not measured, never a pass", ["notmeasured.svg"], 2, "text#axis: rotated or skewed"),
    ("draw.io: overlap, unlabelled, loose edge and contrast", ["flow-bad.drawio"], 1, "RESULT fail: 4 finding(s): 1 contrast, 1 loose-edge, 1 overlap, 1 unlabelled"),
    ("draw.io: edge with no target cell", ["flow-bad.drawio"], 1, "edge edge#loose target at (400,260) touches no shape"),
    ("draw.io: compressed page passes", ["flow-clean.drawio"], 0, "RESULT pass: 2 shape(s), 3 label(s), 1 edge(s)"),
    ("draw.io: unreadable compressed page", ["garbled.drawio"], 2, "compressed in a form this script cannot read"),
    ("Mermaid: style colours, font size, empty label", ["flow-bad.mmd"], 1, "RESULT fail: 3 finding(s): contrast, small-font, unlabelled"),
    ("Mermaid: fill left to the theme fails in dark", ["flow-theme.mmd"], 1, "#cccccc on #f8fafc is 1.53:1 in the dark theme"),
    ("Mermaid: clean styles still leave layout not verified", ["flow-ok.mmd"], 2, "RESULT not verified: layout checks need a rendered SVG"),
    ("not well-formed XML", ["broken.svg"], 2, "not well-formed XML"),
    ("SVG with nothing in it", ["empty.svg"], 2, "no shapes or text found"),
    ("HTML saved as .svg", ["page.svg"], 2, "the root element is <html>"),
    ("XML entities are refused", ["entity.svg"], 2, "declares XML entities"),
    ("unknown format", ["notes.txt"], 2, "not a format this script reads"),
    ("missing file", ["missing.svg"], 2, "blocked: file not found: missing.svg"),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", type=pathlib.Path, default=PACK.parent.parent / ".testrun", help="folder that receives design-diagram-check/run-<n>/")
    parser.add_argument("--verbose", action="store_true", help="print the output of every case, not only of wrong ones")
    args = parser.parse_args()
    work = fresh(args.base.resolve())
    print(f"#### diagram-check  ({work})")
    wrong = 0
    for label, argv, want, needle in CASES:
        done = subprocess.run([sys.executable, SCRIPT, *argv], cwd=work, capture_output=True, text=True)
        output = done.stdout + done.stderr
        ok = done.returncode == want and needle in output
        wrong += not ok
        print(f"{'ok  ' if ok else 'BAD '}exit {done.returncode} (want {want})  {label}")
        if needle not in output:
            print(f"      missing text: {needle!r}")
        if args.verbose or not ok:
            print("      " + "\n      ".join(output.strip().splitlines()[-12:]))
    help_out = subprocess.run([sys.executable, SCRIPT, "--help"], capture_output=True, text=True)
    ok = help_out.returncode == 0 and "loose-edge" in help_out.stdout
    wrong += not ok
    print(f"{'ok  ' if ok else 'BAD '}exit {help_out.returncode} (want 0)  --help explains the rules")
    print(f"diagram-check cases: {len(CASES) + 1} run, {wrong} wrong")
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main())

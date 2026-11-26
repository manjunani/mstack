#!/usr/bin/env python3
"""Run the scripts of the mstack-design skills on hand-written fixtures and generated images.

Each skill gets a fresh folder <base>/design-<skill>/run-<n>/ (default base: .testrun in the
repository root). Fixtures are copied there from tests/scripts/fixtures/<skill>/, so the
originals stay untouched. Every case states the exit code it expects and, where it matters,
a piece of text the output has to contain. PNG test images are made here with the standard
library, with their own encoder, so the skill's reader is not tested against itself only.

Usage: design_cases.py [--only <skill>] [--base <folder>] [--verbose]
Exit 0 when every case behaves as expected, 1 otherwise.
"""
import argparse
import importlib.util
import json
import pathlib
import shutil
import struct
import subprocess
import sys
import zlib

HERE = pathlib.Path(__file__).resolve().parent
PACK = HERE.parent.parent
FIXTURES = HERE / "fixtures"
SKILLS = PACK / "skills"


def fresh(base, skill):
    parent = base / f"design-{skill}"
    n = 1
    while (parent / f"run-{n}").exists():
        n += 1
    work = parent / f"run-{n}"
    source = FIXTURES / skill
    if source.is_dir():
        shutil.copytree(source, work)
    else:
        work.mkdir(parents=True)
    return work


def script(skill, name):
    return str(SKILLS / skill / "scripts" / name)


# ---------- a PNG encoder for test images, separate from the skill's own writer ----------

def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else b if pb <= pc else c


def _chunk(kind, body, break_crc=False):
    crc = zlib.crc32(kind + body) & 0xFFFFFFFF
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc ^ (1 if break_crc else 0))


def png(path, width, height, pixel, channels=3, filters=(0,), depth=8, colour=None, interlace=0, break_crc=False, cut=0):
    """pixel(x, y) returns a tuple with one value per channel. filters is cycled over the rows."""
    bpp = channels * (depth // 8)
    previous = bytes(width * bpp)
    raw = bytearray()
    for y in range(height):
        line = bytearray()
        for x in range(width):
            for value in pixel(x, y)[:channels]:
                line += value.to_bytes(depth // 8, "big")
        kind = filters[y % len(filters)]
        out = bytearray(len(line))
        for i in range(len(line)):
            left = line[i - bpp] if i >= bpp else 0
            up = previous[i]
            corner = previous[i - bpp] if i >= bpp else 0
            guess = (0, left, up, (left + up) // 2, _paeth(left, up, corner))[kind]
            out[i] = (line[i] - guess) & 255
        raw += bytes([kind]) + out
        previous = bytes(line)
    if colour is None:
        colour = {1: 0, 2: 4, 3: 2, 4: 6}[channels]
    data = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, colour, 0, 0, interlace))
    if colour == 3:
        data += _chunk(b"PLTE", bytes(range(256)) * 3)
    data += _chunk(b"IDAT", zlib.compress(bytes(raw)), break_crc) + _chunk(b"IEND", b"")
    pathlib.Path(path).write_bytes(data[:len(data) - cut] if cut else data)


def page(button_x=150, shade=0, header=(17, 24, 39)):
    """A small fake screen: dark header, grey text bars, one blue button."""
    def pixel(x, y):
        if y < 24:
            return (*header, 255)
        if 40 <= y < 46 and 16 <= x < 200 or 56 <= y < 62 and 16 <= x < 170 or 72 <= y < 78 and 16 <= x < 120:
            return (75 + shade, 85 + shade, 99 + shade, 255)
        if 110 <= y < 140 and button_x <= x < button_x + 70:
            return (37, 99 + shade, 235, 255)
        return (255, 255, 255, 255)
    return pixel


def read_bmp(path):
    """Read an uncompressed 24- or 32-bit BMP into rows of RGB bytes. Used to check the PNG reader against the system's decoder."""
    data = pathlib.Path(path).read_bytes()
    offset = struct.unpack("<I", data[10:14])[0]
    width, height = struct.unpack("<ii", data[18:26])
    bits = struct.unpack("<H", data[28:30])[0]
    step = bits // 8
    stride = (width * step + 3) // 4 * 4
    rows = []
    for y in range(abs(height)):
        line = data[offset + y * stride:offset + y * stride + width * step]
        rows.append(bytes(b for x in range(width) for b in (line[x * step + 2], line[x * step + 1], line[x * step])))
    return width, abs(height), rows[::-1] if height > 0 else rows


# ---------- cases ----------

def cases_token_check(work):
    t = script("token-check", "tokens.py")
    return [
        ("two pairs under the limit, one per theme", [t, "contrast", "tokens-bad.css"], 1, "RESULT fail: 2 pair(s)"),
        ("a proposal that keeps the hue is printed", [t, "contrast", "tokens-bad.css"], 1, "#9ca3af -> #677080 keeps the hue"),
        ("every pair passes in light and dark", [t, "contrast", "tokens-good.css"], 0, "checked 6 pair measurements in 2 theme(s)"),
        ("failures waived with a reason", [t, "contrast", "tokens-bad.css", "--waivers", "waivers.json"], 0, "2 waived"),
        ("a waiver without a real reason is refused", [t, "contrast", "tokens-bad.css", "--waivers", "waivers-no-reason.json"], 2, "needs a reason"),
        ("unsupported colour space is not verified, never a pass", [t, "contrast", "tokens-odd.css"], 2, "colour space not supported"),
        ("explicit pairs file", [t, "contrast", "tokens-odd.css", "--pairs", "pairs.json"], 0, "9.52:1"),
        ("Tailwind literal colours, computed entries reported", [t, "contrast", "tokens-bad.css", "--tailwind", "tailwind.config.js"], 1, "1 computed entries"),
        ("Tailwind pair under the limit is found", [t, "contrast", "tokens-bad.css", "--tailwind", "tailwind.config.js"], 1, "tw:paper-foreground #9ca3af on tw:paper #ffffff"),
        ("no tokens in the file", [t, "contrast", "src/app.css"], 2, "no custom properties found"),
        ("missing file", [t, "contrast", "nope.css"], 2, "file not found"),
        ("hard-coded colours and off-scale sizes", [t, "drift", "src", "--css", "tokens-bad.css"], 1, "4 hard-coded colours, 3 off-scale sizes"),
        ("a link target that looks like a hex colour is not counted", [t, "drift", "src", "--css", "tokens-bad.css"], 1, "RESULT fail: 7 value(s)"),
        ("accepted values drop out, unused entries are reported", [t, "drift", "src", "--css", "tokens-bad.css", "--accept", "accept.json"], 1, "accept entry matched nothing"),
        ("clean source passes", [t, "drift", "clean-src", "--css", "tokens-bad.css"], 0, "RESULT pass"),
        ("empty source folder", [t, "drift", "empty-src", "--css", "tokens-bad.css"], 2, "no source files"),
        ("report is written once and never overwritten", [t, "drift", "src", "--css", "tokens-bad.css", "--report", "drift.json"], 1, "report written"),
        ("second report to the same file is refused", [t, "drift", "src", "--css", "tokens-bad.css", "--report", "drift.json"], 1, "already exists"),
    ]


def cases_ui_match(work):
    c = script("ui-match", "compare_png.py")
    png(work / "ref.png", 240, 160, page(), channels=3)
    png(work / "same-rgba-filters.png", 240, 160, page(), channels=4, filters=(0, 1, 2, 3, 4))
    for kind in (1, 2, 3, 4):
        png(work / f"filter{kind}.png", 240, 160, page(), channels=3, filters=(kind,))
    png(work / "noise.png", 240, 160, page(shade=5), channels=4, filters=(4,))
    png(work / "moved.png", 240, 160, page(button_x=120), channels=4, filters=(1, 4))
    png(work / "taller.png", 240, 190, page(), channels=3)
    png(work / "wide.png", 250, 160, page(), channels=3)
    png(work / "double.png", 480, 320, lambda x, y: page()(x // 2, y // 2), channels=4, filters=(3,))
    png(work / "blank.png", 240, 160, lambda x, y: (0, 0, 0, 255), channels=3)
    png(work / "palette.png", 240, 160, lambda x, y: ((x + y) % 256,), channels=1, colour=3)
    png(work / "grey.png", 240, 160, lambda x, y: ((x * y) % 256,), channels=1)
    png(work / "deep.png", 60, 40, lambda x, y: (x * 900, y * 1200, 40000), channels=3, depth=16)
    png(work / "interlaced.png", 240, 160, page(), channels=3, interlace=1)
    png(work / "badcrc.png", 240, 160, page(), channels=3, break_crc=True)
    png(work / "cut.png", 240, 160, page(), channels=3, cut=40)
    (work / "photo.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 64)
    (work / "regions-keep.json").write_text(json.dumps([
        {"name": "header", "x": 0, "y": 0, "width": 240, "height": 24},
        {"name": "text", "x": 0, "y": 24, "width": 240, "height": 76},
        {"name": "button-row", "x": 0, "y": 100, "width": 240, "height": 60, "ignore": True,
         "reason": "The button sits further left on purpose: the product's form layout puts actions under the fields."}]))
    (work / "regions-no-reason.json").write_text(json.dumps([
        {"name": "button-row", "x": 0, "y": 100, "width": 240, "height": 60, "ignore": True}]))
    (work / "regions-outside.json").write_text(json.dumps([{"name": "far", "x": 200, "y": 0, "width": 100, "height": 20}]))
    cases = [
        ("supported file is described", [c, "info", "ref.png"], 0, "240 x 160, 8-bit RGB"),
        ("RGB against RGBA with all five filter types", [c, "compare", "ref.png", "same-rgba-filters.png"], 0, "0 differ"),
        ("small colour noise stays inside the tolerance", [c, "compare", "ref.png", "noise.png"], 0, "RESULT pass"),
        ("the same noise fails at tolerance 2", [c, "compare", "ref.png", "noise.png", "--tolerance", "2"], 1, "RESULT fail"),
        ("a moved button fails in its regions only", [c, "compare", "ref.png", "moved.png", "--grid", "4x4"], 1, "RESULT fail: 4 region(s) differ"),
        ("the difference is kept on purpose with a reason", [c, "compare", "ref.png", "moved.png", "--regions", "regions-keep.json"], 0, "1 kept on purpose"),
        ("ignoring a region without a reason is refused", [c, "compare", "ref.png", "moved.png", "--regions", "regions-no-reason.json"], 2, "without a reason"),
        ("a region outside the image is refused", [c, "compare", "ref.png", "moved.png", "--regions", "regions-outside.json"], 2, "lies outside"),
        ("different height fails", [c, "compare", "ref.png", "taller.png"], 1, "30 px apart"),
        ("widths that are not a 2x or 3x pair", [c, "compare", "ref.png", "wide.png"], 2, "widths differ"),
        ("a 2x screenshot is averaged down", [c, "compare", "ref.png", "double.png"], 0, "averaged down to 240 x 160"),
        ("a flat image is not a render", [c, "compare", "ref.png", "blank.png"], 2, "one flat colour"),
        ("palette PNG is unsupported", [c, "info", "palette.png"], 2, "palette PNG"),
        ("greyscale PNG is unsupported", [c, "info", "grey.png"], 2, "greyscale PNG"),
        ("16-bit PNG is unsupported", [c, "info", "deep.png"], 2, "16 bits per channel"),
        ("interlaced PNG is unsupported", [c, "compare", "ref.png", "interlaced.png"], 2, "interlaced"),
        ("checksum mismatch is caught", [c, "info", "badcrc.png"], 2, "checksum mismatch"),
        ("a file cut short is caught", [c, "info", "cut.png"], 2, "RESULT not verified"),
        ("a JPEG is refused", [c, "compare", "ref.png", "photo.jpg"], 2, "not a PNG file"),
        ("a missing file is refused", [c, "compare", "ref.png", "nope.png"], 2, "cannot read"),
        ("a bad grid is refused", [c, "compare", "ref.png", "moved.png", "--grid", "lots"], 2, "bad --grid"),
        ("a diff image is written", [c, "compare", "ref.png", "moved.png", "--diff", "diff.png"], 1, "differing pixels marked"),
        ("the diff image is itself a readable PNG", [c, "info", "diff.png"], 0, "supported"),
        ("an existing diff file is not overwritten", [c, "compare", "ref.png", "moved.png", "--diff", "diff.png"], 2, "does not overwrite"),
        ("round 1 is recorded", [c, "compare", "ref.png", "moved.png", "--record"], 1, "round 1 of 3"),
        ("round 2 is recorded", [c, "compare", "ref.png", "moved.png", "--record"], 1, "round 2 of 3"),
        ("round 3 still differing ends as blocked", [c, "compare", "ref.png", "moved.png", "--record"], 2, "blocked: 3 rounds used"),
    ]
    for kind in (1, 2, 3, 4):
        cases.append((f"filter type {kind} decodes to the same pixels as type 0", [c, "compare", "ref.png", f"filter{kind}.png", "--tolerance", "0", "--max-diff", "0"], 0, "0 differ"))
    return cases


def extra_ui_match(work):
    """Check the PNG reader against the operating system's own decoder, when one is present (sips on macOS)."""
    if shutil.which("sips") is None:
        return [("not run", "PNG reader against the system decoder: sips is not on this machine")]
    spec = importlib.util.spec_from_file_location("compare_png", script("ui-match", "compare_png.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    png(work / "busy.png", 97, 61, lambda x, y: ((x * 7 + y * 3) % 256, (x * x + y) % 256, (x ^ (y * 5)) % 256, 255), channels=3, filters=(4, 3, 1, 2, 0))
    out = []
    for source, label in (("busy.png", "test encoder, five filter types"), ("resaved.png", "PNG written by the system encoder")):
        if source == "resaved.png":
            done = subprocess.run(["sips", "-s", "format", "png", str(work / "busy.png"), "--out", str(work / source)], capture_output=True, text=True)
            if done.returncode != 0 or not (work / source).exists():
                out.append(("not run", f"{label}: sips could not re-save the image"))
                continue
        bmp = work / (source + ".bmp")
        done = subprocess.run(["sips", "-s", "format", "bmp", str(work / source), "--out", str(bmp)], capture_output=True, text=True)
        if done.returncode != 0 or not bmp.exists():
            out.append(("not run", f"{label}: sips could not convert to BMP"))
            continue
        try:
            width, height, channels, rows = module.read_png(work / source)
        except module.Unsupported as exc:
            out.append(("not run", f"{label}: the system wrote a variant the reader refuses ({exc})"))
            continue
        ours = module.to_rgb(rows, channels)
        bw, bh, theirs = read_bmp(bmp)
        same = (width, height) == (bw, bh) and ours == theirs
        out.append(("ok" if same else "BAD", f"{label}: {width} x {height} pixels equal to the system decoder's BMP"))
    return out


def cases_design_review(work):
    c = script("design-review", "check_page.py")
    return [
        ("merge three good views", [c, "merge", "good-320.json", "good-768.json", "good-1440.json", "--out", "good.json"], 0, "3 view(s)"),
        ("good page at 320, 768, 1440 passes", [c, "check", "good.json"], 0, "0 blocking"),
        ("merge with the bad 320 view", [c, "merge", "bad-320.json", "good-768.json", "good-1440.json", "--out", "bad.json"], 0, "3 view(s)"),
        ("bad page blocks on overflow, contrast, names, targets, placeholders", [c, "check", "bad.json"], 1, "11 blocking finding(s): clipped, contrast, no-name, page-overflow, placeholder-text, small-target"),
        ("taste traits only warn", [c, "check", "bad.json"], 1, "default-gradient"),
        ("disabled control is not judged for contrast", [c, "check", "bad.json"], 1, "RESULT fail"),
        ("merging a view twice is refused", [c, "merge", "good-320.json", "good-320.json", "--out", "twice.json"], 2, "both hold view"),
        ("merge never overwrites", [c, "merge", "good-320.json", "--out", "good.json"], 2, "does not overwrite"),
        ("missing widths are not verified", [c, "check", "good-320.json"], 2, "no view at 768 px"),
        ("missing dark theme is not verified", [c, "check", "good.json", "--themes", "light,dark"], 2, "theme dark"),
        ("text on an image cannot be judged", [c, "check", "photo-320.json", "--widths", "320"], 2, "could not be judged"),
        ("waiver with a reason clears it", [c, "check", "photo-320.json", "--widths", "320", "--waivers", "waivers.json"], 0, "1 waived"),
        ("waiver without a reason is refused", [c, "check", "photo-320.json", "--widths", "320", "--waivers", "waivers-no-reason.json"], 2, "needs a reason"),
        ("views with no elements are not a capture", [c, "check", "empty-view.json"], 2, "holds no elements"),
        ("axe output is not a snapshot", [c, "check", "not-a-snapshot.json"], 2, "not a snapshot"),
        ("snapshot taken by collect.js in a real browser", [c, "check", "live-626.json", "--widths", "626"], 1, "10 blocking finding(s)"),
        ("collector caught opacity-faded text", [c, "check", "live-626.json", "--widths", "626"], 1, "Faded by opacity."),
    ]


def cases_a11y_audit(work):
    a = script("a11y-audit", "audit.py")
    (work / "proj").mkdir()
    return [
        ("needs: no Playwright or axe-core in an empty project", [a, "needs", "--root", "proj"], 2, "blocked:"),
        ("violations at AA fail; best-practice only warns", [a, "check", "--axe", "axe-before.json", "--keyboard", "keys-good.json"], 1, "2 accessibility failure(s)"),
        ("save the baseline before fixing", [a, "check", "--axe", "axe-before.json", "--keyboard", "keys-good.json", "--root", "proj", "--save-baseline"], 1, "baseline saved"),
        ("a second save is refused", [a, "check", "--axe", "axe-before.json", "--keyboard", "keys-good.json", "--root", "proj", "--save-baseline"], 2, "already exists"),
        ("after the fix: both fixed, pass", [a, "check", "--axe", "axe-after.json", "--keyboard", "keys-good.json", "--root", "proj", "--baseline"], 0, "2 fixed, 0 remaining, 0 new"),
        ("a new violation after the fix is caught", [a, "check", "--axe", "axe-after-new.json", "--keyboard", "keys-good.json", "--root", "proj", "--baseline"], 1, "1 new"),
        ("level A ignores the AA contrast rule", [a, "check", "--axe", "axe-before.json", "--keyboard", "keys-good.json", "--level", "A"], 1, "1 accessibility failure(s)"),
        ("keyboard: invisible focus, trap, unreached control, failed Escape", [a, "check", "--axe", "axe-after.json", "--keyboard", "keys-bad.json"], 1, "5 accessibility failure(s)"),
        ("no keyboard log is not verified", [a, "check", "--axe", "axe-after.json"], 2, "no keyboard log"),
        ("an undecided axe result needs a look", [a, "check", "--axe", "axe-after-new.json", "--keyboard", "keys-good.json", "--level", "AA"], 1, "LOOK"),
        ("a scan with no rule results did not run", [a, "check", "--axe", "axe-empty.json", "--keyboard", "keys-good.json"], 2, "did not run"),
        ("a snapshot is not axe output", [a, "check", "--axe", "keys-good.json"], 2, "not axe-core output"),
        ("baseline compare with no baseline", [a, "check", "--axe", "axe-after.json", "--keyboard", "keys-good.json", "--root", "nowhere", "--baseline"], 2, "no baseline"),
        ("a run with fewer pages than the baseline is not verified", [a, "check", "--axe", "axe-after.json", "--root", "proj", "--baseline"], 2, "keyboard pass"),
    ]


def extra_a11y(work):
    if __import__("shutil").which("node") is None:
        return [("not run", "run_axe.mjs: node is not on this machine")]
    done = subprocess.run(["node", script("a11y-audit", "run_axe.mjs"), "--url", "http://localhost:1/", "--out", str(work / "scan")],
                          cwd=work / "proj", capture_output=True, text=True)
    ok = done.returncode == 2 and "blocked:" in done.stdout
    return [("ok" if ok else "BAD", f"run_axe.mjs without Playwright and axe-core ends as blocked (exit {done.returncode})")]


def cases_ui_copy(work):
    c = script("ui-copy", "copy_check.py")
    return [
        ("bad flow: mixed names, vague buttons, dead-end and raw errors, placeholders", ["check", "--snapshot", "flow-bad.json"], 1, "9 string(s) to fix or answer: dead-end-error, mixed-names, placeholder, raw-error, vague-button"),
        ("an error with a fix button beside it is not a dead end", ["check", "--snapshot", "flow-bad.json"], 1, "dead-end-error         \"Something went wrong.\""),
        ("a sentence with the word 'activity' is not read as raw error text", ["check", "--snapshot", "flow-bad.json"], 1, "RESULT fail"),
        ("good flow passes", ["check", "--snapshot", "flow-good.json"], 0, "0 blocking"),
        ("source scan of a JSX file; commented-out text ignored", ["check", "--source", "src"], 1, "4 string(s) to fix or answer"),
        ("strings file", ["check", "--strings", "strings.json"], 1, "mixed-names"),
        ("answered findings with reasons pass", ["check", "--strings", "strings.json", "--answers", "answers.json"], 0, "2 answered"),
        ("answer without a reason is refused", ["check", "--strings", "strings.json", "--answers", "answers-no-reason.json"], 2, "needs a reason"),
        ("no markup means no strings: not verified", ["check", "--source", "no-markup"], 2, "no strings found"),
        ("inventory file written", ["check", "--snapshot", "flow-good.json", "--inventory", "inventory.json"], 0, "inventory written"),
        ("inventory never overwritten", ["check", "--snapshot", "flow-good.json", "--inventory", "inventory.json"], 2, "does not overwrite"),
    ]


def cases_ui_build(work):
    u = script("ui-build", "lint_ui.py")
    return [
        ("unfinished work blocks", [u, "lint", "bad"], 1, "dead-handler, dead-link, filler-text, focus-removed, invented-proof, work-marker"),
        ("default looks are listed as warnings", [u, "lint", "bad"], 1, "violet-gradient"),
        ("default looks alone never block", [u, "lint", "warn-only"], 0, "everything-rounded"),
        ("outline removed with a focus-visible ring is fine", [u, "lint", "warn-only"], 0, "0 blocking"),
        ("empty folder is not verified", [u, "lint", "nothing-here"], 2, "does not exist"),
        ("round 1", [u, "round", "--note", "320 and 1440 px looked at; header wraps at 320"], 0, "round 1 of 3"),
        ("a round with no real note is refused", [u, "round", "--note", "ok"], 2, "--note"),
        ("round 2", [u, "round", "--note", "header fixed; empty state still missing"], 0, "round 2 of 3"),
        ("round 3", [u, "round", "--note", "empty state added; contrast of the badge still low"], 0, "round 3 of 3"),
        ("round 4 is refused", [u, "round", "--note", "one more try at the badge colour"], 2, "blocked: the limit of 3"),
        ("a finished page with sample input hints, a skeleton pulse and one centred note is silent",
         [u, "lint", "clean"], 0, "0 blocking, 0 default-look warnings"),
    ] + [
        (f"{rule} {'blocks' if level == 'BLOCK' else 'warns'} at {name}:{line}", [u, "lint", f"looks/{name}"],
         1 if level == "BLOCK" else 0, f"{level:5} {rule:18} {name}:{line}:")
        for level, rule, name, line in UI_BUILD_LOOKS
    ]


# one fixture per rule added on 2026-11-25; each file trips only its own rule
UI_BUILD_LOOKS = [
    ("BLOCK", "placeholder-name", "placeholder-name.jsx", 4),
    ("BLOCK", "placeholder-image", "placeholder-image.html", 3),
    ("BLOCK", "example-link", "example-link.html", 3),
    ("warn", "blue-violet-gradient", "blue-violet-gradient.jsx", 3),
    ("warn", "stock-brand-colour", "stock-brand-colour.jsx", 4),
    ("warn", "stock-hero-phrases", "stock-hero-phrases.html", 3),
    ("warn", "announce-pill", "announce-pill.jsx", 4),
    ("warn", "ai-sparkle", "ai-sparkle.tsx", 4),
    ("warn", "blurred-blobs", "blurred-blobs.jsx", 4),
    ("warn", "grey-on-colour", "grey-on-colour.jsx", 4),
    ("warn", "attention-animation", "attention-animation.jsx", 4),
    ("warn", "hover-lift", "hover-lift.jsx", 4),
    ("warn", "eyebrow-labels", "eyebrow-labels.html", 2),
    ("warn", "gradient-buttons", "gradient-buttons.html", 4),
    ("warn", "stock-cta", "stock-cta.jsx", 5),
    ("warn", "centred-everything", "centred-everything.html", 2),
    ("warn", "same-card-everywhere", "same-card-everywhere.jsx", 4),
    ("warn", "icon-tile-grid", "icon-tile-grid.jsx", 4),
    ("warn", "uniform-card-copy", "uniform-card-copy.html", 2),
    ("warn", "font-weight-sprawl", "font-weight-sprawl.css", 1),
    ("warn", "skipped-heading", "skipped-heading.html", 4),
]


def cases_brand_kit(work):
    b = script("brand-kit", "brand.py")
    return [
        ("off-kit colours, fonts and a banned phrase are listed with places", [b, "check", "--files", "site"], 1, "2 off-kit colours, 1 off-kit fonts, 1 banned phrases"),
        ("a near-identical brand colour counts as in the kit", [b, "check", "--files", "site"], 1, "RESULT fail: 4 off-kit item(s)"),
        ("a link to #top is not read as a colour", [b, "check", "--files", "site"], 1, "OFF voice"),
        ("clean stylesheet passes", [b, "check", "--files", "clean"], 0, "0 off-kit colours"),
        ("page snapshot checked against the kit", [b, "check", "--snapshot", "snap.json"], 1, "inter"),
        ("unconfirmed brand file is refused", [b, "check", "--brand", "brand-draft.json", "--files", "clean"], 2, "not confirmed"),
        ("unconfirmed brand file with --draft runs", [b, "check", "--brand", "brand-draft.json", "--files", "clean", "--draft"], 1, "draft, not confirmed"),
        ("missing brand file", [b, "check", "--brand", "nope.json", "--files", "clean"], 2, "cannot read brand file"),
        ("nothing to check", [b, "check"], 2, "give --snapshot or --files"),
        ("init writes a starting file", [b, "init", "--out", "new-brand.json"], 0, "wrote new-brand.json"),
        ("init never overwrites", [b, "init", "--out", "new-brand.json"], 2, "does not overwrite"),
    ]


def prepare(skill, work):
    """Copy shared fixtures a skill reuses from another skill's folder."""
    if skill == "brand-kit":
        shutil.copy(FIXTURES / "design-review" / "bad-320.json", work / "snap.json")


GROUPS = {
    "design-review": (cases_design_review, None),
    "a11y-audit": (cases_a11y_audit, extra_a11y),
    "token-check": (cases_token_check, None),
    "ui-build": (cases_ui_build, None),
    "ui-match": (cases_ui_match, extra_ui_match),
    "ui-copy": (cases_ui_copy, None),
    "brand-kit": (cases_brand_kit, None),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", choices=sorted(GROUPS), help="run one skill's cases")
    parser.add_argument("--base", type=pathlib.Path, default=PACK.parent.parent / ".testrun", help="folder that receives design-<skill>/run-<n>/")
    parser.add_argument("--verbose", action="store_true", help="print the output of every case, not only of wrong ones")
    args = parser.parse_args()
    total = wrong = skipped = 0
    for skill, (build, extra) in GROUPS.items():
        if args.only and skill != args.only:
            continue
        work = fresh(args.base.resolve(), skill)
        print(f"#### {skill}  ({work})")
        ran = bad = 0
        prepare(skill, work)
        for label, argv, want, needle in build(work):
            if skill == "ui-copy":
                argv = [script("ui-copy", "copy_check.py"), *argv]
            done = subprocess.run([sys.executable, *argv] if argv[0].endswith(".py") else argv, cwd=work, capture_output=True, text=True)
            output = done.stdout + done.stderr
            ok = done.returncode == want and (needle is None or needle in output)
            ran += 1
            bad += not ok
            print(f"{'ok  ' if ok else 'BAD '}exit {done.returncode} (want {want})  {label}")
            if not ok and needle and needle not in output:
                print(f"      missing text: {needle!r}")
            if args.verbose or not ok:
                print("      " + "\n      ".join(output.strip().splitlines()[-12:]))
        for status, line in (extra(work) if extra else []):
            if status == "not run":
                skipped += 1
            else:
                ran += 1
                bad += status != "ok"
            print(f"{status:4}{'' if status == 'not run' else ' '} {line}" if status != "not run" else f"not run: {line}")
        print(f"     {skill}: {ran} cases, {bad} wrong")
        total += ran
        wrong += bad
    print(f"design cases: {total} run, {wrong} wrong, {skipped} not run")
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main())

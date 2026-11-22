"""Script test for image-batch: preview and full run with each tool found, location data removal, and failing outputs.

Test images are made with ffmpeg; two JPEGs get a hand-built EXIF block with GPS coordinates.
Usage: image_batch_cases.py <new folder>   (for example .testrun/media-image-batch)
"""
import argparse
import hashlib
import shutil
import struct
import subprocess
import sys

import fixtures as fx

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("folder")
root = fx.new_folder(parser.parse_args().folder)
I = fx.script("image-batch", "image_batch.py")
c = fx.Cases("image-batch cases")
sys.path.insert(0, str(fx.PACK / "skills" / "image-batch" / "scripts"))
import image_batch as ib  # noqa: E402  (used only to read dimensions and location in the outputs)


def gps_block():
    entries = 2
    gps_at = 8 + 2 + entries * 12 + 4
    ifd0 = struct.pack("<H", entries) + struct.pack("<HHIHH", 0x0112, 3, 1, 1, 0) + struct.pack("<HHII", 0x8825, 4, 1, gps_at) + struct.pack("<I", 0)
    data_at = gps_at + 2 + 4 * 12 + 4
    gps = (struct.pack("<H", 4) + struct.pack("<HHI", 1, 2, 2) + b"N\0\0\0" + struct.pack("<HHII", 2, 5, 3, data_at)
           + struct.pack("<HHI", 3, 2, 2) + b"E\0\0\0" + struct.pack("<HHII", 4, 5, 3, data_at + 24) + struct.pack("<I", 0)
           + struct.pack("<6I", 17, 1, 23, 1, 1000, 100) + struct.pack("<6I", 78, 1, 29, 1, 2000, 100))
    body = b"Exif\0\0" + b"II*\0" + struct.pack("<I", 8) + ifd0 + gps
    return b"\xff\xe1" + struct.pack(">H", len(body) + 2) + body


src = root / "photos"
src.mkdir()
for name, size in (("a-wide", "1200x800"), ("b-tall", "600x900"), ("c-square", "700x700"), ("d-small", "320x240")):
    fx.ffmpeg("-f", "lavfi", "-i", f"testsrc2=size={size}:rate=1:duration=1", "-frames:v", "1", "-q:v", "3", src / f"{name}.jpg")
fx.ffmpeg("-f", "lavfi", "-i", "testsrc2=size=900x500:rate=1:duration=1", "-frames:v", "1", src / "e-shot.png")
for name in ("a-wide", "b-tall"):
    raw = (src / f"{name}.jpg").read_bytes()
    (src / f"{name}.jpg").write_bytes(raw[:2] + gps_block() + raw[2:])
(src / "notes.txt").write_text("not an image\n")
before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in src.iterdir()}
c.expect("two inputs hold GPS data before the run", sum(ib.has_location(p) for p in src.glob("*.jpg")) == 2)

out = c.case("tools: list", [I, "tools"], 0)
tools = [t for t in ("sips", "imagemagick", "pillow") if t in out.split("would use")[0]]
print(f"tools found on this machine: {tools}")
for tool in tools:
    o = root / f"out-{tool}"
    c.case(f"{tool}: preview of 3", [I, "preview", src, "--out", o, "--width", "400", "--height", "300", "--tool", tool], 2, must_print="preview images pass")
    c.expect(f"{tool}: preview holds exactly 3 files", len(list((o / "preview").iterdir())) == 3)
    c.case(f"{tool}: full run, cover 400x300", [I, "run", src, "--out", o, "--width", "400", "--height", "300", "--tool", tool], 0)
    outs = sorted((o / "images").iterdir())
    c.expect(f"{tool}: 5 outputs, all 400x300, none with location", len(outs) == 5 and all(ib.dims(p) == (400, 300) for p in outs)
             and not any(ib.has_location(p) for p in outs), str([(p.name, ib.dims(p)) for p in outs]))
    c.case(f"{tool}: within 500x500 as PNG", [I, "run", src, "--out", root / f"within-{tool}", "--width", "500", "--height", "500",
                                             "--mode", "within", "--format", "png", "--tool", tool], 0)
    c.case(f"{tool}: size limit of 2 KB cannot be met", [I, "run", src, "--out", root / f"tiny-{tool}", "--width", "400", "--height", "300",
                                                         "--max-kb", "2", "--tool", tool], 1, must_print="limit 2.0 KB")

if not tools:
    c.case("no tool: run is blocked", [I, "run", src, "--out", root / "x", "--width", "10", "--height", "10"], 2, must_print="blocked")
first = root / f"out-{tools[0]}" / "images" if tools else None
if first:
    c.case("check: the first tool's output again", [I, "check", src, "--out", first, "--width", "400", "--height", "300"], 0)
    c.case("check: against the wrong size", [I, "check", src, "--out", first, "--width", "640", "--height", "480"], 1, must_print="needs exactly 640x480")
    shutil.copy(src / "a-wide.jpg", root / "planted.jpg")
    (first / "c-square.jpg").unlink()
    c.case("check: one output missing", [I, "check", src, "--out", first, "--width", "400", "--height", "300"], 1, must_print="5 inputs but 4 outputs")
    shutil.copy(root / "planted.jpg", first / "c-square.jpg")
    out = c.case("check: an output with location data and the wrong size", [I, "check", src, "--out", first, "--width", "400", "--height", "300"], 1)
    c.expect("both faults are named for that file", "c-square.jpg: is 1200x800" in out and "location (GPS)" in out)
    c.case("run: into a folder that already holds files", [I, "run", src, "--out", root / f"out-{tools[0]}", "--width", "400", "--height", "300"], 2, must_print="already holds files")
c.case("run: output folder is the input folder", [I, "run", src, "--out", src, "--width", "400", "--height", "300"], 2, must_print="blocked")
c.case("run: input is not a folder", [I, "run", src / "notes.txt", "--out", root / "y", "--width", "4", "--height", "3"], 2, must_print="blocked")
empty = root / "empty"
empty.mkdir()
c.case("run: folder with no images", [I, "run", empty, "--out", root / "z", "--width", "4", "--height", "3"], 0, must_print="nothing to do")
c.expect("the input images are byte-for-byte unchanged", before == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in src.iterdir()})
raise SystemExit(c.finish())

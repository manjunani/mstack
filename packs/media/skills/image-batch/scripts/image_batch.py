#!/usr/bin/env python3
"""Apply one resize, crop and export to a folder of images, writing into a NEW folder, and check every output.

  tools    show which image tool will be used (sips on macOS, ImageMagick, or Pillow), in that order
  preview  process the first few images into <out>/preview and check them; the user looks before the full run
  run      process every image into <out> and check them all
  check    check an output folder against its inputs without processing anything

Modes:  cover   exact WIDTHxHEIGHT; the image is scaled to fill the frame and the overflow is cut off evenly
        within  scaled to fit inside WIDTHxHEIGHT; nothing is cut off; one side may be smaller
Checks per output: the file exists, its dimensions (read from the file itself, not from the tool), its size
under --max-kb, and no location (GPS) data. Also: one output for every input.
Location data is removed by this script after the tool writes, by dropping the EXIF and XMP blocks of JPEG files
and the eXIf chunk of PNG files. That also drops other metadata such as camera model and orientation.

Background removal is not part of this version.
Exit codes: 0 = pass, 1 = fail, 2 = not verified or blocked. Inputs are only read.
"""
import argparse
import pathlib
import shutil
import struct
import subprocess
import sys

KINDS = {".jpg", ".jpeg", ".png", ".heic", ".tif", ".tiff", ".webp", ".gif", ".bmp"}
PILLOW_CODE = r"""
import sys
from PIL import Image, ImageOps
src, dst, mode, w, h, fmt, q = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5]), sys.argv[6], int(sys.argv[7])
im = ImageOps.exif_transpose(Image.open(src))
if fmt == "jpeg" and im.mode not in ("RGB", "L"):
    im = im.convert("RGB")
im = ImageOps.fit(im, (w, h), Image.LANCZOS) if mode == "cover" else ImageOps.contain(im, (w, h), Image.LANCZOS)
im.save(dst, "JPEG" if fmt == "jpeg" else "PNG", **({"quality": q} if fmt == "jpeg" else {}))
"""


def end(code, line):
    print(line)
    return code


def find_tool(wanted=None):
    have = []
    if sys.platform == "darwin" and shutil.which("sips"):
        have.append("sips")
    if shutil.which("magick") or shutil.which("convert"):
        have.append("imagemagick")
    if subprocess.run([sys.executable, "-c", "import PIL"], capture_output=True).returncode == 0:
        have.append("pillow")
    if wanted:
        return wanted if wanted in have else None, have
    return (have[0] if have else None), have


def dims(path):
    """Width and height read from the file's own header (JPEG or PNG). None for other formats."""
    data = pathlib.Path(path).read_bytes()
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                return None
            marker = data[i + 1]
            length = struct.unpack(">H", data[i + 2:i + 4])[0]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return w, h
            i += 2 + length
    return None


def tiff_has_gps(tiff):
    try:
        order = "<" if tiff[:2] == b"II" else ">"
        offset = struct.unpack(order + "I", tiff[4:8])[0]
        count = struct.unpack(order + "H", tiff[offset:offset + 2])[0]
        for n in range(count):
            tag = struct.unpack(order + "H", tiff[offset + 2 + 12 * n:offset + 4 + 12 * n])[0]
            if tag == 0x8825:
                return True
    except struct.error:
        return True  # unreadable EXIF is treated as possibly holding location
    return False


def has_location(path):
    data = pathlib.Path(path).read_bytes()
    if b"GPSLatitude" in data or b"GPSLongitude" in data:
        return True
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 4 < len(data) and data[i] == 0xFF and data[i + 1] != 0xDA:
            length = struct.unpack(">H", data[i + 2:i + 4])[0]
            body = data[i + 4:i + 2 + length]
            if data[i + 1] == 0xE1 and body[:6] == b"Exif\0\0" and tiff_has_gps(body[6:]):
                return True
            i += 2 + length
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        i = 8
        while i + 8 <= len(data):
            length, kind = struct.unpack(">I4s", data[i:i + 8])
            if kind == b"eXIf" and tiff_has_gps(data[i + 8:i + 8 + length]):
                return True
            i += 12 + length
    return False


def strip_metadata(path):
    """Drop EXIF and XMP from a JPEG, and eXIf from a PNG, in a file this script just wrote."""
    data = pathlib.Path(path).read_bytes()
    out = None
    if data[:2] == b"\xff\xd8":
        out, i = bytearray(data[:2]), 2
        while i + 4 <= len(data) and data[i] == 0xFF and data[i + 1] != 0xDA:
            length = struct.unpack(">H", data[i + 2:i + 4])[0]
            body = data[i + 4:i + 2 + length]
            if not (data[i + 1] == 0xE1 and (body[:6] == b"Exif\0\0" or body[:29] == b"http://ns.adobe.com/xap/1.0/\0")):
                out += data[i:i + 2 + length]
            i += 2 + length
        out += data[i:]
    elif data[:8] == b"\x89PNG\r\n\x1a\n":
        out, i = bytearray(data[:8]), 8
        while i + 8 <= len(data):
            length, kind = struct.unpack(">I4s", data[i:i + 8])
            if kind != b"eXIf" and not (kind == b"iTXt" and b"XML:com.adobe.xmp" in data[i + 8:i + 30]):
                out += data[i:i + 12 + length]
            i += 12 + length
    if out is not None and bytes(out) != data:
        pathlib.Path(path).write_bytes(bytes(out))


def run(call):
    done = subprocess.run(call, capture_output=True, text=True)
    return done.returncode == 0, (done.stderr or done.stdout).strip()[-200:]


def process(tool, src, dst, args):
    fmt = "jpeg" if args.format == "jpeg" else "png"
    w, h = args.width, args.height
    if tool == "pillow":
        return run([sys.executable, "-c", PILLOW_CODE, str(src), str(dst), args.mode, str(w), str(h), fmt, str(args.quality)])
    if tool == "imagemagick":
        exe = shutil.which("magick") or shutil.which("convert")
        geo = [f"-resize", f"{w}x{h}^", "-gravity", "center", "-extent", f"{w}x{h}"] if args.mode == "cover" else ["-resize", f"{w}x{h}"]
        return run([exe, str(src), "-auto-orient", *geo, "-quality", str(args.quality), f"{fmt}:{dst}"])
    # sips: read the size, scale, then crop the copy it wrote.
    probe = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(src)], capture_output=True, text=True).stdout
    try:
        sw = int(probe.split("pixelWidth:")[1].split()[0])
        sh = int(probe.split("pixelHeight:")[1].split()[0])
    except (IndexError, ValueError):
        return False, "sips could not read the image size"
    scale = max(w / sw, h / sh) if args.mode == "cover" else min(w / sw, h / sh)
    nw, nh = max(1, round(sw * scale)), max(1, round(sh * scale))
    if args.mode == "cover":
        nw, nh = max(nw, w), max(nh, h)
    ok, why = run(["sips", "-s", "format", fmt, "-s", "formatOptions", str(args.quality) if fmt == "jpeg" else "default",
                   "--resampleHeightWidth", str(nh), str(nw), str(src), "--out", str(dst)])
    if ok and args.mode == "cover":
        ok, why = run(["sips", "--cropToHeightWidth", str(h), str(w), str(dst)])
    return ok, why


def inputs(folder):
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in KINDS)


def out_name(src, args):
    return src.stem + (".jpg" if args.format == "jpeg" else ".png")


def check_one(dst, args):
    faults = []
    if not dst.exists() or dst.stat().st_size == 0:
        return ["missing or empty"]
    size = dims(dst)
    if size is None:
        return ["dimensions could not be read from the file"]
    w, h = size
    if args.mode == "cover" and (w, h) != (args.width, args.height):
        faults.append(f"is {w}x{h}, needs exactly {args.width}x{args.height}")
    if args.mode == "within" and (w > args.width or h > args.height or (w != args.width and h != args.height)):
        faults.append(f"is {w}x{h}, needs to fit inside {args.width}x{args.height} touching one side")
    kb = dst.stat().st_size / 1024
    if args.max_kb and kb > args.max_kb:
        faults.append(f"is {kb:.0f} KB, limit {args.max_kb} KB")
    if has_location(dst):
        faults.append("still holds location (GPS) data")
    return faults


def check_folder(srcs, out, args):
    faults = []
    expected = {out_name(s, args) for s in srcs}
    if len(expected) != len(srcs):
        faults.append("two inputs share a name and would write the same output file")
    present = {p.name for p in out.iterdir() if p.is_file() and p.suffix.lower() in KINDS} if out.exists() else set()
    for name in sorted(expected):
        for f in check_one(out / name, args):
            faults.append(f"{name}: {f}")
    print(f"inputs: {len(srcs)}; outputs found: {len(present & expected)}; extra files in the output folder: {len(present - expected)}")
    if len(present & expected) != len(srcs):
        faults.append(f"{len(srcs)} inputs but {len(present & expected)} outputs")
    return faults


def guard(args):
    if not args.src.is_dir():
        sys.exit(end(2, f"blocked: {args.src} is not a folder"))
    if args.out.resolve() == args.src.resolve():
        sys.exit(end(2, "blocked: the output folder is the input folder; give a new folder"))
    srcs = inputs(args.src)
    if not srcs:
        sys.exit(end(0, f"RESULT pass: no images in {args.src}; nothing to do"))
    return srcs


def batch(args, srcs, out):
    tool, have = find_tool(args.tool)
    if tool is None:
        return end(2, f"blocked: no image tool found{' named ' + args.tool if args.tool else ''} (have: {', '.join(have) or 'none'}). "
                      "On macOS sips is built in; elsewhere ImageMagick or Pillow is needed. Ask the user before installing anything.")
    if out.exists() and any(out.iterdir()):
        return end(2, f"blocked: {out} already holds files; give a new folder so nothing is overwritten")
    out.mkdir(parents=True, exist_ok=True)
    print(f"tool: {tool}; {args.mode} {args.width}x{args.height}, {args.format}" + (f", at most {args.max_kb} KB" if args.max_kb else ""))
    failed = []
    for src in srcs:
        dst = out / out_name(src, args)
        ok, why = process(tool, src, dst, args)
        if ok and dst.exists():
            strip_metadata(dst)
        else:
            failed.append(f"{src.name}: the tool failed ({why})")
    faults = failed + check_folder(srcs, out, args)
    for f in faults[:30]:
        print("  FAIL " + f)
    if faults:
        return end(1, f"RESULT fail: {len(faults)} problem(s); first: {faults[0]}")
    return None


def cmd_tools(args):
    tool, have = find_tool()
    print(f"available: {', '.join(have) or 'none'}; would use: {tool or 'none'}")
    return end(0 if tool else 2, "RESULT pass: a tool is available" if tool else "blocked: no image tool; on macOS sips is built in, elsewhere ImageMagick or Pillow")


def cmd_preview(args):
    srcs = guard(args)
    folder = args.out / "preview"
    code = batch(args, srcs[:args.count], folder)
    if code is not None:
        return code
    for p in sorted(folder.iterdir()):
        print(f"  preview: {p}  {dims(p)}")
    return end(2, f"RESULT not verified: {min(args.count, len(srcs))} preview images pass the checks. Open them and show the user; "
                  "the script cannot judge whether the crop cuts off something that matters. After a yes, run 'run' with the same settings.")


def cmd_run(args):
    srcs = guard(args)
    code = batch(args, srcs, args.out / "images")
    if code is not None:
        return code
    return end(0, f"RESULT pass: {len(srcs)} images written to {args.out / 'images'}; every one has the right dimensions, size and no location data")


def cmd_check(args):
    srcs = guard(args)
    faults = check_folder(srcs, args.out, args)
    for f in faults[:30]:
        print("  FAIL " + f)
    if faults:
        return end(1, f"RESULT fail: {len(faults)} problem(s); first: {faults[0]}")
    return end(0, f"RESULT pass: {len(srcs)} outputs checked")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("tools", help="show the image tool that will be used")
    for name in ("preview", "run", "check"):
        p = sub.add_parser(name)
        p.add_argument("src", type=pathlib.Path, help="folder of images (only read)")
        p.add_argument("--out", type=pathlib.Path, required=True, help="new folder (preview/ and images/ go inside); for check, the folder of outputs")
        p.add_argument("--width", type=int, required=True)
        p.add_argument("--height", type=int, required=True)
        p.add_argument("--mode", choices=["cover", "within"], default="cover")
        p.add_argument("--format", choices=["jpeg", "png"], default="jpeg")
        p.add_argument("--quality", type=int, default=82, help="JPEG quality 1-100 (default 82)")
        p.add_argument("--max-kb", type=float, help="largest allowed output file, in kilobytes")
        p.add_argument("--tool", choices=["sips", "imagemagick", "pillow"], help="force one tool")
        p.add_argument("--count", type=int, default=3, help="images in the preview (default 3)")
    args = parser.parse_args()
    return {"tools": cmd_tools, "preview": cmd_preview, "run": cmd_run, "check": cmd_check}[args.action](args)


if __name__ == "__main__":
    sys.exit(main())

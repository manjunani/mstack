#!/usr/bin/env python3
"""Read a PNG with the standard library and say whether it shows a real picture or a blank one.

  pngstat.py FILE [FILE ...]      print size and pixel statistics for each file and a verdict

What it reads: the PNG signature, every chunk's checksum, the header, the palette and the
pixel data (all five row filters, 8 and 16 bit, grey, colour, palette, with or without alpha).
What it measures, on the rows between the ignored top and bottom bands (status bar, home bar):
the share of the most common colour, the number of different colours, the spread of
brightness and the share of fully transparent pixels.

Limits and thresholds come from ../references/image-check.json. They are mstack defaults,
not platform facts; the script prints that.

Large images: when `sips` exists (macOS) a reduced copy is made in a scratch folder and the
statistics are taken from that copy. The original is never changed. Without `sips`, or with
--pure, the full image is decoded in Python, which is slow for a phone screenshot.
An interlaced PNG is read only through `sips`.

Exit codes: 0 = every file is a real picture
            1 = at least one file is blank, broken or not a PNG
            2 = a file is missing, the thresholds file is missing, or a file could not be judged
"""
import argparse
import collections
import hashlib
import itertools
import json
import math
import pathlib
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

SIGNATURE = b"\x89PNG\r\n\x1a\n"
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
DEPTHS = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
LIMITS_FILE = pathlib.Path(__file__).resolve().parent.parent / "references" / "image-check.json"
PURE_PIXELS = 600_000  # above this, a reduced copy is used when sips exists


class PngError(ValueError):
    """The file is not a PNG this reader can decode."""


def load_limits(path=LIMITS_FILE):
    """Return ({name: value}, notes). Raises OSError or ValueError when the data file is unusable."""
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    values, notes = {}, []
    for name, entry in data.items():
        if isinstance(entry, dict) and "value" in entry:
            values[name] = entry["value"]
            if not entry.get("verified"):
                notes.append(f"{name}={entry['value']} ({entry.get('source', 'no source')}; set {entry.get('checked', '?')})")
    need = ("blank_top_colour_fraction", "min_luma_stddev", "transparent_fraction",
            "ignore_top_fraction", "ignore_bottom_fraction", "min_side_px")
    missing = [n for n in need if n not in values]
    if missing:
        raise ValueError(f"thresholds file lacks: {', '.join(missing)}")
    return values, notes


def read_chunks(data):
    if data[:8] != SIGNATURE:
        raise PngError("not a PNG: the first eight bytes are not the PNG signature")
    pos, out = 8, []
    while pos + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        crc = data[pos + 8 + length:pos + 12 + length]
        if len(body) != length or len(crc) != 4:
            raise PngError(f"cut short inside the {kind.decode('latin-1')} chunk")
        if zlib.crc32(kind + body) & 0xFFFFFFFF != struct.unpack(">I", crc)[0]:
            raise PngError(f"checksum of the {kind.decode('latin-1')} chunk is wrong")
        out.append((kind, body))
        pos += 12 + length
        if kind == b"IEND":
            break
    if not out or out[0][0] != b"IHDR" or len(out[0][1]) != 13:
        raise PngError("no header chunk")
    if out[-1][0] != b"IEND":
        raise PngError("no end chunk: the file is cut short")
    return out


def header(chunks):
    width, height, depth, colour, compression, flt, interlace = struct.unpack(">IIBBBBB", chunks[0][1])
    if width == 0 or height == 0:
        raise PngError("width or height is zero")
    if colour not in CHANNELS or depth not in DEPTHS[colour]:
        raise PngError(f"colour type {colour} with bit depth {depth} is not valid")
    if compression != 0 or flt != 0:
        raise PngError("unknown compression or filter method")
    kinds = {k for k, _ in chunks}
    return {"width": width, "height": height, "depth": depth, "colour_type": colour,
            "interlaced": bool(interlace), "alpha": colour in (4, 6) or b"tRNS" in kinds}


def _add_bytes(a, b):
    """Byte-wise (a + b) mod 256 for two equal-length byte strings, without a Python loop."""
    n = len(a)
    x, y = int.from_bytes(a, "big"), int.from_bytes(b, "big")
    low = int.from_bytes(b"\x7f" * n, "big")
    high = int.from_bytes(b"\x80" * n, "big")
    return (((x & low) + (y & low)) ^ ((x ^ y) & high)).to_bytes(n, "big")


def unfilter(raw, stride, bpp, height):
    """Undo the five PNG row filters. Returns a list of rows (bytes)."""
    if len(raw) < (stride + 1) * height:
        raise PngError(f"pixel data is short: {len(raw)} bytes for {height} rows of {stride + 1}")
    rows, prev = [], bytes(stride)
    for y in range(height):
        start = y * (stride + 1)
        kind = raw[start]
        line = raw[start + 1:start + 1 + stride]
        if kind == 0:
            cur = line
        elif kind == 2:
            cur = _add_bytes(line, prev)
        elif kind == 1:
            out = bytearray(stride)
            for c in range(bpp):
                out[c::bpp] = bytes(itertools.accumulate(line[c::bpp], lambda p, q: (p + q) & 255))
            cur = bytes(out)
        elif kind == 3:
            out = bytearray(line)
            for i in range(stride):
                left = out[i - bpp] if i >= bpp else 0
                out[i] = (out[i] + ((left + prev[i]) >> 1)) & 255
            cur = bytes(out)
        elif kind == 4:
            out = bytearray(line)
            for i in range(stride):
                a = out[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                out[i] = (out[i] + pred) & 255
            cur = bytes(out)
        else:
            raise PngError(f"row {y} uses unknown filter {kind}")
        rows.append(cur)
        prev = cur
    return rows


def decode(data):
    """Return (info, rows, palette, transparency) for a non-interlaced PNG."""
    chunks = read_chunks(data)
    info = header(chunks)
    if info["interlaced"]:
        raise PngError("interlaced PNG: this reader needs sips to convert it")
    packed = b"".join(body for kind, body in chunks if kind == b"IDAT")
    if not packed:
        raise PngError("no pixel data chunk")
    try:
        raw = zlib.decompress(packed)
    except zlib.error as exc:
        raise PngError(f"pixel data does not decompress ({exc})")
    channels, depth = CHANNELS[info["colour_type"]], info["depth"]
    stride = (info["width"] * channels * depth + 7) // 8
    bpp = max(1, channels * depth // 8)
    rows = unfilter(raw, stride, bpp, info["height"])
    palette = next((body for kind, body in chunks if kind == b"PLTE"), b"")
    transparency = next((body for kind, body in chunks if kind == b"tRNS"), b"")
    if info["colour_type"] == 3 and not palette:
        raise PngError("palette image with no palette")
    return info, rows, palette, transparency


def _samples(row, width, depth):
    """Unpack one row of 1, 2 or 4 bit samples into a list of integers."""
    out, mask = [], (1 << depth) - 1
    for byte in row:
        for shift in range(8 - depth, -1, -depth):
            out.append((byte >> shift) & mask)
    return out[:width]


def _rgba(key, info, palette, transparency):
    """Turn one stored pixel (bytes, or an int for packed samples) into 8-bit (r, g, b, a)."""
    colour, depth = info["colour_type"], info["depth"]
    if isinstance(key, int):
        if colour == 3:
            p = palette[key * 3:key * 3 + 3]
            if len(p) < 3:
                raise PngError("pixel points outside the palette")
            return p[0], p[1], p[2], transparency[key] if key < len(transparency) else 255
        v = key * 255 // ((1 << depth) - 1)
        return v, v, v, 255
    step = 2 if depth == 16 else 1
    vals = key[::step]
    if colour == 3:
        return _rgba(vals[0], info, palette, transparency)
    if colour == 0:
        return vals[0], vals[0], vals[0], 255
    if colour == 4:
        return vals[0], vals[0], vals[0], vals[1]
    if colour == 2:
        return vals[0], vals[1], vals[2], 255
    return vals[0], vals[1], vals[2], vals[3]


def measure(info, rows, palette, transparency, limits, band=True):
    width, height = info["width"], info["height"]
    top = int(height * limits["ignore_top_fraction"]) if band else 0
    bottom = height - int(height * limits["ignore_bottom_fraction"]) if band else height
    if bottom - top < 1:
        top, bottom = 0, height
    step = max(1, int(math.sqrt((bottom - top) * width / 250_000)))
    channels, depth = CHANNELS[info["colour_type"]], info["depth"]
    counts = collections.Counter()
    for y in range(top, bottom, step):
        row = rows[y]
        if depth < 8:
            counts.update(_samples(row, width, depth)[::step])
        else:
            bpp = channels * depth // 8
            counts.update(row[i:i + bpp] for i in range(0, len(row), bpp * step))
    total = sum(counts.values())
    lum_sum = lum_sq = transparent = 0.0
    lum_min, lum_max = 255.0, 0.0
    merged = collections.Counter()
    for key, n in counts.items():
        r, g, b, a = _rgba(key, info, palette, transparency)
        merged[(r, g, b, a)] += n
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        lum_sum += lum * n
        lum_sq += lum * lum * n
        lum_min, lum_max = min(lum_min, lum), max(lum_max, lum)
        if a == 0:
            transparent += n
    mean = lum_sum / total
    return {"sampled": total, "rows_used": [top, bottom], "distinct": len(merged),
            "top_fraction": max(merged.values()) / total,
            "luma_min": round(lum_min, 1), "luma_max": round(lum_max, 1),
            "luma_stddev": round(math.sqrt(max(0.0, lum_sq / total - mean * mean)), 2),
            "transparent_fraction": transparent / total}


def _reduced_copy(path, scratch):
    """Ask sips for a small non-interlaced PNG copy. Returns the copy's path or None."""
    sips = shutil.which("sips")
    if not sips:
        return None
    out = pathlib.Path(scratch) / "reduced.png"
    try:
        done = subprocess.run([sips, "-s", "format", "png", "-Z", "640", str(path), "--out", str(out)],
                              capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out if done.returncode == 0 and out.exists() and out.stat().st_size > 0 else None


def stats(path, limits, pure=False, band=True):
    """Return a dict. Keys: ok, error, width, height, alpha, sha256, via, and the measurements."""
    path = pathlib.Path(path)
    result = {"file": str(path), "ok": False}
    try:
        data = path.read_bytes()
    except OSError as exc:
        result["error"] = f"cannot read: {exc.strerror or exc}"
        result["missing"] = True
        return result
    result["bytes"] = len(data)
    result["sha256"] = hashlib.sha256(data).hexdigest()
    try:
        info = header(read_chunks(data))
    except PngError as exc:
        result["error"] = str(exc)
        return result
    result.update(width=info["width"], height=info["height"], alpha=info["alpha"],
                  colour_type=info["colour_type"], depth=info["depth"], interlaced=info["interlaced"])
    big = info["width"] * info["height"] > PURE_PIXELS
    try:
        if (big or info["interlaced"]) and not pure:
            with tempfile.TemporaryDirectory(prefix="mstack-pngstat-") as scratch:
                copy = _reduced_copy(path, scratch)
                if copy is not None:
                    small = decode(copy.read_bytes())
                    result.update(measure(*small, limits, band=band))
                    result["via"] = f"reduced copy made by sips ({small[0]['width']}x{small[0]['height']})"
                    result["ok"] = True
                    return result
        decoded = decode(data)
        result.update(measure(*decoded, limits, band=band))
        result["via"] = "full decode in Python"
        result["ok"] = True
    except PngError as exc:
        result["error"] = str(exc)
        result["unjudged"] = info["interlaced"]
    return result


def judge(result, limits):
    """Return (verdict, reason). Verdict is 'real', 'blank', 'invalid', 'missing' or 'unknown'."""
    if result.get("missing"):
        return "missing", result["error"]
    if not result["ok"]:
        return ("unknown" if result.get("unjudged") else "invalid"), result["error"]
    if min(result["width"], result["height"]) < limits["min_side_px"]:
        return "invalid", f"{result['width']}x{result['height']} is smaller than {limits['min_side_px']} px on one side"
    if result["transparent_fraction"] >= limits["transparent_fraction"]:
        return "blank", f"{result['transparent_fraction']:.1%} of the pixels are fully transparent"
    if result["top_fraction"] >= limits["blank_top_colour_fraction"]:
        return "blank", f"{result['top_fraction']:.2%} of the pixels are one colour"
    if result["luma_stddev"] < limits["min_luma_stddev"]:
        return "blank", f"brightness barely varies (spread {result['luma_stddev']})"
    return "real", (f"{result['distinct']} colours, most common colour {result['top_fraction']:.1%}, "
                    f"brightness spread {result['luma_stddev']}")


def describe(result, limits):
    """One line for a report, and the verdict."""
    verdict, reason = judge(result, limits)
    size = f"{result['width']}x{result['height']}" if "width" in result else "no size"
    return verdict, f"{verdict:8} {size:11} {result['file']}: {reason}"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="+", help="PNG files to read")
    parser.add_argument("--pure", action="store_true", help="never use sips; decode the full image in Python")
    parser.add_argument("--whole", action="store_true", help="measure every row; do not ignore the top and bottom bands")
    parser.add_argument("--json", action="store_true", help="print the measurements as JSON as well")
    args = parser.parse_args()
    try:
        limits, notes = load_limits()
    except (OSError, ValueError) as exc:
        print(f"blocked: the thresholds file {LIMITS_FILE} cannot be used ({exc})")
        return 2
    if notes:
        print("note: image thresholds are mstack defaults, not platform facts: " + "; ".join(notes))
    verdicts = []
    for name in args.files:
        result = stats(name, limits, pure=args.pure, band=not args.whole)
        verdict, line = describe(result, limits)
        verdicts.append(verdict)
        print(line)
        if result.get("ok"):
            print(f"         read by: {result['via']}; rows {result['rows_used'][0]} to {result['rows_used'][1]}; {result['sampled']} pixels sampled")
        if args.json:
            print(json.dumps(result, indent=2))
    if "missing" in verdicts or "unknown" in verdicts:
        which = [n for n, v in zip(args.files, verdicts) if v in ("missing", "unknown")]
        print(f"RESULT not verified: could not judge {', '.join(which)}")
        return 2
    bad = [n for n, v in zip(args.files, verdicts) if v != "real"]
    if bad:
        print(f"RESULT fail: {len(bad)} of {len(verdicts)} images are blank or broken: {', '.join(bad)}")
        return 1
    print(f"RESULT pass: {len(verdicts)} of {len(verdicts)} images are real pictures")
    return 0


if __name__ == "__main__":
    sys.exit(main())

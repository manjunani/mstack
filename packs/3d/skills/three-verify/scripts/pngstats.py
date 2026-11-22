#!/usr/bin/env python3
"""Decide from the pixels whether a PNG shows a rendered picture or a blank one. Standard library only.

  pngstats.py stats <png> [<png> ...]   spread, dominant colour and transparency of each image
  pngstats.py diff <before.png> <after.png>   how far two images of the same size differ

Reads 8-bit, non-interlaced PNG (grey, grey+alpha, RGB, RGBA, palette). Anything else ends as not verified,
because a guess about pixels is worse than no answer.

A screenshot command succeeds on a black canvas. These numbers are the real assertion:
  spread          the largest standard deviation of the red, green and blue channels (0 = one flat colour)
  dominant share  the share of sampled pixels that have the most common colour
  transparent     the share of pixels with alpha 0

Limits come from references/render_thresholds.json next to this script (dated, unverified working values).
Exit codes: 0 = every image holds a picture (stats) or the two images agree (diff)
            1 = a blank or single-colour image (stats), or images that differ too much (diff)
            2 = not verified: a file is missing, not a PNG, or in a form this reader does not decode
"""
import argparse
import collections
import hashlib
import json
import pathlib
import struct
import sys
import zlib

SIGNATURE = b"\x89PNG\r\n\x1a\n"
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
THRESHOLDS = pathlib.Path(__file__).resolve().parent.parent / "references" / "render_thresholds.json"
SAMPLE = 200000


class Unreadable(Exception):
    pass


def decode(path):
    """Return (width, height, channels, pixel bytes) with channels 3 (RGB) or 4 (RGBA). Raises Unreadable."""
    try:
        data = pathlib.Path(path).read_bytes()
    except OSError as exc:
        raise Unreadable(f"cannot read file: {exc.strerror}") from exc
    if data[:8] != SIGNATURE:
        raise Unreadable("not a PNG (wrong signature)")
    pos, header, palette, alpha_table, idat = 8, None, None, None, []
    while pos + 8 <= len(data):
        length, kind = struct.unpack_from(">I4s", data, pos)
        body = data[pos + 8:pos + 8 + length]
        if len(body) < length:
            raise Unreadable(f"chunk {kind.decode('latin-1')} is cut short")
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body[:13])
        elif kind == b"PLTE":
            palette = body
        elif kind == b"tRNS":
            alpha_table = body
        elif kind == b"IDAT":
            idat.append(body)
        elif kind == b"IEND":
            break
        pos += 12 + length
    if header is None:
        raise Unreadable("no IHDR chunk")
    width, height, depth, colour, _, _, interlace = header
    if depth != 8:
        raise Unreadable(f"bit depth {depth}; only 8-bit PNG is decoded")
    if interlace:
        raise Unreadable("interlaced PNG is not decoded")
    if colour not in CHANNELS:
        raise Unreadable(f"unknown colour type {colour}")
    if width == 0 or height == 0:
        raise Unreadable("zero width or height")
    bpp = CHANNELS[colour]
    stride = width * bpp
    try:
        raw = zlib.decompress(b"".join(idat))
    except zlib.error as exc:
        raise Unreadable(f"image data does not decompress: {exc}") from exc
    if len(raw) < (stride + 1) * height:
        raise Unreadable("image data is shorter than width x height")
    out = bytearray(stride * height)
    prev = bytearray(stride)
    pos = 0
    for y in range(height):
        kind = raw[pos]
        line = bytearray(raw[pos + 1:pos + 1 + stride])
        pos += 1 + stride
        if kind == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 255
        elif kind == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif kind == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 255
        elif kind == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        elif kind != 0:
            raise Unreadable(f"row {y} uses unknown filter {kind}")
        out[y * stride:(y + 1) * stride] = line
        prev = line
    if colour == 2 or colour == 6:
        return width, height, bpp, bytes(out)
    if colour == 0:
        return width, height, 3, bytes(v for g in out for v in (g, g, g))
    if colour == 4:
        grey, alpha = out[0::2], out[1::2]
        return width, height, 4, bytes(v for g, a in zip(grey, alpha) for v in (g, g, g, a))
    if palette is None:
        raise Unreadable("palette image without a PLTE chunk")
    table = [tuple(palette[i:i + 3]) for i in range(0, len(palette) - 2, 3)]
    alphas = list(alpha_table or b"") + [255] * len(table)
    try:
        return width, height, 4, bytes(v for index in out for v in (*table[index], alphas[index]))
    except IndexError as exc:
        raise Unreadable("a pixel points outside the palette") from exc


def _spread(channel):
    counts = collections.Counter(channel)
    total = len(channel)
    mean = sum(value * n for value, n in counts.items()) / total
    variance = sum(n * (value - mean) ** 2 for value, n in counts.items()) / total
    return mean, variance ** 0.5


def measure(path):
    """Return a dict of pixel statistics for one PNG. Raises Unreadable."""
    width, height, channels, pixels = decode(path)
    red, green, blue = pixels[0::channels], pixels[1::channels], pixels[2::channels]
    means, spreads = zip(*(_spread(c) for c in (red, green, blue)))
    step = max(1, (width * height) // SAMPLE)
    sample = collections.Counter(zip(red[::step], green[::step], blue[::step]))
    colour, hits = sample.most_common(1)[0]
    transparent = 0.0
    if channels == 4:
        alpha = pixels[3::4]
        transparent = alpha.count(0) / len(alpha)
    return {
        "file": str(path), "width": width, "height": height,
        "mean": [round(m, 2) for m in means], "spread": round(max(spreads), 3),
        "dominant_colour": list(colour), "dominant_share": round(hits / sum(sample.values()), 5),
        "distinct_colours_sampled": len(sample), "transparent_share": round(transparent, 5),
        "pixel_hash": hashlib.sha256(pixels).hexdigest()[:16],
    }


def load_thresholds(path=THRESHOLDS):
    """Return (dict of name -> value, list of names that are unverified). Raises Unreadable when the file is unusable."""
    try:
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Unreadable(f"thresholds file {path} cannot be read: {exc}") from exc
    values, unverified = {}, []
    for name, entry in data.get("thresholds", {}).items():
        values[name] = entry["value"]
        if not entry.get("verified"):
            unverified.append(name)
    for name in ("min_spread", "max_dominant_share", "max_transparent_share", "max_mean_difference", "max_changed_share"):
        if name not in values:
            raise Unreadable(f"thresholds file {path} has no entry '{name}'")
    return values, unverified


def judge(stats, limits):
    """Return a list of reasons why this image is not a picture. An empty list means it holds one."""
    reasons = []
    if stats["spread"] < limits["min_spread"]:
        reasons.append(f"flat: spread {stats['spread']} is under {limits['min_spread']}")
    if stats["dominant_share"] > limits["max_dominant_share"]:
        reasons.append(f"single colour: {stats['dominant_share']:.1%} of pixels are {stats['dominant_colour']}")
    if stats["transparent_share"] > limits["max_transparent_share"]:
        reasons.append(f"transparent: {stats['transparent_share']:.1%} of pixels have alpha 0")
    return reasons


def difference(before, after):
    """Return mean absolute channel difference (0 to 255) and the share of pixels that changed visibly. Raises Unreadable."""
    w1, h1, c1, p1 = decode(before)
    w2, h2, c2, p2 = decode(after)
    if (w1, h1) != (w2, h2):
        raise Unreadable(f"sizes differ: {w1}x{h1} and {w2}x{h2}; render both at the same size")
    total = changed = 0
    for offset in range(3):
        a, b = p1[offset::c1], p2[offset::c2]
        total += sum(abs(x - y) for x, y in zip(a, b))
    step = max(1, (w1 * h1) // SAMPLE)
    picks = range(0, w1 * h1, step)
    for i in picks:
        if max(abs(p1[i * c1 + k] - p2[i * c2 + k]) for k in range(3)) > 16:
            changed += 1
    return {"width": w1, "height": h1, "mean_difference": round(total / (w1 * h1 * 3), 3),
            "changed_share": round(changed / len(picks), 5)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--thresholds", type=pathlib.Path, default=THRESHOLDS, help="limits file (default: the skill's own)")
    parser.add_argument("--json", action="store_true", help="print one JSON object")
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("stats", help="is each image a picture or a blank?")
    one.add_argument("png", nargs="+")
    two = sub.add_parser("diff", help="compare two images of the same size")
    two.add_argument("before")
    two.add_argument("after")
    args = parser.parse_args()
    try:
        limits, unverified = load_thresholds(args.thresholds)
    except Unreadable as exc:
        print(f"RESULT not verified: {exc}")
        return 2
    note = f"limits are unverified working values: {', '.join(unverified)}" if unverified else ""

    if args.command == "diff":
        try:
            result = difference(args.before, args.after)
        except Unreadable as exc:
            print(f"RESULT not verified: {exc}")
            return 2
        over = []
        if result["mean_difference"] > limits["max_mean_difference"]:
            over.append(f"mean difference {result['mean_difference']} is over {limits['max_mean_difference']}")
        if result["changed_share"] > limits["max_changed_share"]:
            over.append(f"{result['changed_share']:.1%} of pixels changed, limit {limits['max_changed_share']:.1%}")
        print(json.dumps(result) if args.json else
              f"{result['width']}x{result['height']}: mean difference {result['mean_difference']} of 255, changed pixels {result['changed_share']:.2%}")
        if note:
            print(note)
        if over:
            print("RESULT fail: " + "; ".join(over))
            return 1
        print("RESULT pass")
        return 0

    rows, blank, unread = [], [], []
    for name in args.png:
        try:
            stats = measure(name)
        except Unreadable as exc:
            unread.append(f"{name}: {exc}")
            continue
        stats["problems"] = judge(stats, limits)
        rows.append(stats)
        if stats["problems"]:
            blank.append(f"{name} ({stats['problems'][0]})")
    if args.json:
        print(json.dumps({"images": rows, "unreadable": unread}, indent=2))
    else:
        for stats in rows:
            verdict = "BLANK " + "; ".join(stats["problems"]) if stats["problems"] else "picture"
            print(f"{stats['file']}: {stats['width']}x{stats['height']} spread {stats['spread']} "
                  f"dominant {stats['dominant_share']:.1%} transparent {stats['transparent_share']:.1%} -> {verdict}")
        for line in unread:
            print(f"not read: {line}")
    if note:
        print(note)
    if blank:
        print("RESULT fail: " + "; ".join(blank))
        return 1
    if unread:
        print("RESULT not verified: " + "; ".join(unread))
        return 2
    print("RESULT pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())

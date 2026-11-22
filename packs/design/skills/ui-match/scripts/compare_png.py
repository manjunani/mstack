#!/usr/bin/env python3
"""Compare a rendered screenshot with a reference image, region by region. Standard library only.

  info     print the size and PNG variant of a file, and whether this script can read it
  compare  compare reference and actual by region and report the share of differing pixels

Supported PNG: 8 bits per channel, colour type RGB (2) or RGBA (6), not interlaced.
Not supported (exit 2 with the reason): palette images (type 3), greyscale (types 0 and 4),
16-bit channels, and Adam7 interlacing. JPEG, WebP and other formats are not read at all.
Take the screenshot again as a plain PNG, or export the mockup as 24-bit or 32-bit PNG.

Regions are a grid (--grid 6x8, columns x rows) or a JSON list of named boxes (--regions).
A pixel differs when any channel is more than --tolerance away. A region fails when the
share of differing pixels is above its limit. A region with "ignore": true needs a reason.

Exit codes: 0 = every region is within its limit
            1 = at least one region differs, or the heights differ
            2 = not verified or blocked: unreadable or unsupported file, widths that cannot
                be matched, a blank image, a bad regions file, or the round limit reached
With --record the round is added to .mstack/ui-match/rounds.json under --root. With --diff a
new PNG marking the differing pixels is written. Existing files are never overwritten.
"""
import argparse
import datetime
import json
import pathlib
import struct
import sys
import zlib

HERE = pathlib.Path(__file__).resolve().parent
DEFAULTS = HERE.parent / "references" / "defaults.json"
SIGNATURE = b"\x89PNG\r\n\x1a\n"
COLOUR_TYPES = {0: "greyscale", 2: "RGB", 3: "palette", 4: "greyscale with alpha", 6: "RGBA"}


class Unsupported(Exception):
    pass


def read_png(path):
    """Return (width, height, channels, rows) where rows is a list of bytes objects, one per scanline."""
    try:
        data = pathlib.Path(path).read_bytes()
    except OSError as exc:
        raise Unsupported(f"cannot read {path}: {exc}")
    if not data.startswith(SIGNATURE):
        raise Unsupported(f"{path} is not a PNG file (wrong signature). JPEG, WebP and other formats are not supported.")
    pos, header, idat, ended = 8, None, [], False
    while pos + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        crc = data[pos + 8 + length:pos + 12 + length]
        if len(body) != length or len(crc) != 4:
            raise Unsupported(f"{path} is cut short inside a {kind.decode('latin-1')} chunk")
        if zlib.crc32(kind + body) & 0xFFFFFFFF != struct.unpack(">I", crc)[0]:
            raise Unsupported(f"{path} is damaged: checksum mismatch in the {kind.decode('latin-1')} chunk")
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat.append(body)
        elif kind == b"IEND":
            ended = True
            break
        pos += 12 + length
    if header is None or not idat or not ended:
        raise Unsupported(f"{path} is incomplete: header, image data or end marker is missing")
    width, height, depth, colour, _, _, interlace = header
    name = COLOUR_TYPES.get(colour, f"type {colour}")
    if depth != 8:
        raise Unsupported(f"{path} has {depth} bits per channel ({name}); only 8-bit RGB and RGBA are supported")
    if colour not in (2, 6):
        raise Unsupported(f"{path} is a {name} PNG; only RGB and RGBA are supported")
    if interlace != 0:
        raise Unsupported(f"{path} is interlaced (Adam7); only non-interlaced PNG is supported")
    if width == 0 or height == 0:
        raise Unsupported(f"{path} has no pixels")
    channels = 3 if colour == 2 else 4
    stride = width * channels
    try:
        raw = zlib.decompress(b"".join(idat))
    except zlib.error as exc:
        raise Unsupported(f"{path} is damaged: image data does not decompress ({exc})")
    if len(raw) != (stride + 1) * height:
        raise Unsupported(f"{path} is damaged: expected {(stride + 1) * height} bytes of image data, found {len(raw)}")
    rows, previous = [], bytes(stride)
    for y in range(height):
        start = y * (stride + 1)
        kind = raw[start]
        line = bytearray(raw[start + 1:start + 1 + stride])
        if kind == 1:  # Sub
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 255
        elif kind == 2:  # Up
            for i in range(stride):
                line[i] = (line[i] + previous[i]) & 255
        elif kind == 3:  # Average
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((left + previous[i]) >> 1)) & 255
        elif kind == 4:  # Paeth
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = previous[i]
                c = previous[i - channels] if i >= channels else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        elif kind != 0:
            raise Unsupported(f"{path} is damaged: unknown filter type {kind} on row {y}")
        previous = bytes(line)
        rows.append(previous)
    return width, height, channels, rows


def write_png(path, width, height, rows):
    """Write 8-bit RGB rows as a PNG with no filtering."""
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + bytes(row) for row in rows)
    pathlib.Path(path).write_bytes(SIGNATURE + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                                   + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def to_rgb(rows, channels):
    """Flatten RGBA onto white so that transparent areas compare as the page would show them."""
    if channels == 3:
        return rows
    out = []
    for row in rows:
        line = bytearray(len(row) // 4 * 3)
        for i in range(len(row) // 4):
            a = row[i * 4 + 3]
            if a == 255:
                line[i * 3:i * 3 + 3] = row[i * 4:i * 4 + 3]
            else:
                for k in range(3):
                    line[i * 3 + k] = (row[i * 4 + k] * a + 255 * (255 - a) + 127) // 255
        out.append(bytes(line))
    return out


def shrink(rows, width, factor):
    """Average factor x factor blocks, for a screenshot taken at 2x or 3x device pixels."""
    out = []
    new_width = width // factor
    area = factor * factor
    for y in range(len(rows) // factor):
        block = rows[y * factor:(y + 1) * factor]
        line = bytearray(new_width * 3)
        for x in range(new_width):
            for k in range(3):
                total = 0
                for row in block:
                    base = x * factor * 3 + k
                    total += sum(row[base + j * 3] for j in range(factor))
                line[x * 3 + k] = (total + area // 2) // area
        out.append(bytes(line))
    return new_width, out


def is_blank(rows):
    first = rows[0][:3]
    return all(row == first * (len(row) // 3) for row in rows)


def stop(message, blocked=False):
    print(message)
    print(("blocked: " if blocked else "RESULT not verified: ") + message)
    return 2


def load_defaults():
    data = json.loads(DEFAULTS.read_text(encoding="utf-8"))
    return {k: v["value"] for k, v in data.items() if isinstance(v, dict)}


def grid_regions(spec, width, height):
    try:
        cols, rows = (int(n) for n in spec.lower().split("x"))
        if cols < 1 or rows < 1 or cols > width or rows > height:
            raise ValueError
    except ValueError:
        return None
    out = []
    for r in range(rows):
        for c in range(cols):
            x0, x1 = width * c // cols, width * (c + 1) // cols
            y0, y1 = height * r // rows, height * (r + 1) // rows
            out.append({"name": f"r{r + 1}c{c + 1}", "x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0})
    return out


def cmd_info(args):
    try:
        width, height, channels, rows = read_png(args.file)
    except Unsupported as exc:
        return stop(str(exc))
    blank = is_blank(to_rgb(rows, channels))
    print(f"{args.file}: {width} x {height}, 8-bit {'RGB' if channels == 3 else 'RGBA'}, non-interlaced: supported")
    if blank:
        return stop(f"{args.file} is one flat colour: not a render")
    print("RESULT pass")
    return 0


def cmd_compare(args):
    defaults = load_defaults()
    tolerance = defaults["channel_tolerance"] if args.tolerance is None else args.tolerance
    limit = defaults["region_max_diff_percent"] if args.max_diff is None else args.max_diff
    max_rounds = int(defaults["max_rounds"])
    for target in (args.diff, args.report):
        if target and pathlib.Path(target).exists():
            return stop(f"{target} already exists and this script does not overwrite files; give a new name")
    try:
        ref_w, ref_h, ref_c, ref_rows = read_png(args.reference)
        act_w, act_h, act_c, act_rows = read_png(args.actual)
    except Unsupported as exc:
        return stop(str(exc))
    ref_rows, act_rows = to_rgb(ref_rows, ref_c), to_rgb(act_rows, act_c)
    for label, path, rows in (("reference", args.reference, ref_rows), ("actual", args.actual, act_rows)):
        if is_blank(rows):
            return stop(f"the {label} image {path} is one flat colour: not a render")
    print(f"reference {args.reference}: {ref_w} x {ref_h}")
    print(f"actual    {args.actual}: {act_w} x {act_h}")
    if act_w != ref_w:
        big, small = max(act_w, ref_w), min(act_w, ref_w)
        if big % small == 0 and big // small in (2, 3):
            factor = big // small
            if act_w > ref_w:
                act_w, act_rows = shrink(act_rows, act_w, factor)
                act_h = len(act_rows)
                print(f"the actual image is {factor}x the reference width; it was averaged down to {act_w} x {act_h}")
            else:
                ref_w, ref_rows = shrink(ref_rows, ref_w, factor)
                ref_h = len(ref_rows)
                print(f"the reference is {factor}x the actual width; it was averaged down to {ref_w} x {ref_h}")
        else:
            return stop(f"widths differ ({ref_w} and {act_w}) and are not a 2x or 3x pair: render the page at the reference width and take the screenshot again")
    height = min(ref_h, act_h)
    if args.regions:
        try:
            regions = json.loads(pathlib.Path(args.regions).read_text(encoding="utf-8"))
            if isinstance(regions, dict):
                regions = regions.get("regions")
            assert isinstance(regions, list) and regions
        except (OSError, ValueError, AssertionError) as exc:
            return stop(f"cannot use regions file {args.regions}: it needs a JSON list of boxes ({exc})")
        for region in regions:
            if not isinstance(region, dict) or not all(isinstance(region.get(k), int) for k in ("x", "y", "width", "height")) or not region.get("name"):
                return stop(f"regions file: each region needs name, x, y, width, height as whole numbers: {json.dumps(region)}")
            if region.get("ignore") and len(str(region.get("reason", "")).strip()) < 8:
                return stop(f"regions file: region '{region['name']}' is ignored without a reason of at least 8 characters")
            if region["width"] < 1 or region["height"] < 1 or region["x"] < 0 or region["y"] < 0 or region["x"] + region["width"] > ref_w:
                return stop(f"regions file: region '{region['name']}' lies outside the {ref_w} px wide image")
    else:
        regions = grid_regions(args.grid or defaults["grid"], ref_w, height)
        if regions is None:
            return stop(f"bad --grid value {args.grid!r}: use columns x rows, for example 6x8")
    diff_rows = [bytearray(b"\xff" * (ref_w * 3)) for _ in range(height)] if args.diff else None
    results, failed, ignored, outside = [], [], [], []
    for region in regions:
        x0, y0 = region["x"], region["y"]
        x1, y1 = x0 + region["width"], min(region["y"] + region["height"], height)
        if y0 >= height:
            outside.append(region["name"])
            continue
        differing = total = 0
        for y in range(y0, y1):
            a, b = ref_rows[y][x0 * 3:x1 * 3], act_rows[y][x0 * 3:x1 * 3]
            total += x1 - x0
            if a == b:
                continue
            for i in range(0, len(a), 3):
                if abs(a[i] - b[i]) > tolerance or abs(a[i + 1] - b[i + 1]) > tolerance or abs(a[i + 2] - b[i + 2]) > tolerance:
                    differing += 1
                    if diff_rows is not None:
                        diff_rows[y][x0 * 3 + i:x0 * 3 + i + 3] = b"\xe0\x10\x60"
        share = 100.0 * differing / total if total else 0.0
        region_limit = region.get("max_diff", limit)
        row = {"name": region["name"], "x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0,
               "diff_percent": round(share, 2), "limit": region_limit}
        if region.get("ignore"):
            row["ignored"] = region["reason"]
            ignored.append(row)
        elif share > region_limit:
            failed.append(row)
        results.append(row)
    for row in results:
        mark = "skip" if "ignored" in row else ("DIFF" if row in failed else "ok  ")
        note = f"  kept on purpose: {row['ignored']}" if "ignored" in row else ""
        print(f"{mark} {row['name']:14} x {row['x']:5} y {row['y']:5} {row['width']:5} x {row['height']:<5} {row['diff_percent']:6.2f}% differ (limit {row['limit']}%){note}")
    for name in outside:
        print(f"DIFF {name}: this region starts below the shorter image, so it could not be compared")
    height_gap = abs(ref_h - act_h)
    if height_gap:
        print(f"DIFF height: reference is {ref_h} px tall, actual is {act_h} px tall ({height_gap} px apart); only the top {height} px were compared")
    print(f"compared {len(results)} regions at tolerance {tolerance} per channel: {len(failed)} differ, {len(ignored)} kept on purpose")
    if args.diff:
        write_png(args.diff, ref_w, height, diff_rows)
        print(f"differing pixels marked in {args.diff}")
    if args.report:
        pathlib.Path(args.report).write_text(json.dumps({"reference": str(args.reference), "actual": str(args.actual),
                                                         "tolerance": tolerance, "regions": results,
                                                         "height_gap": height_gap}, indent=2) + "\n", encoding="utf-8")
        print(f"report written to {args.report}")
    bad = bool(failed or outside or height_gap > defaults["height_gap_px"])
    if args.record:
        state = pathlib.Path(args.root) / ".mstack" / "ui-match"
        state.mkdir(parents=True, exist_ok=True)
        ledger = state / "rounds.json"
        rounds = json.loads(ledger.read_text(encoding="utf-8")) if ledger.exists() else []
        rounds.append({"round": len(rounds) + 1, "when": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                       "reference": str(args.reference), "actual": str(args.actual),
                       "failed": [r["name"] for r in failed] + outside, "height_gap": height_gap})
        ledger.write_text(json.dumps(rounds, indent=2) + "\n", encoding="utf-8")
        print(f"round {len(rounds)} of {max_rounds} recorded in {ledger}")
        if bad and len(rounds) >= max_rounds:
            names = ", ".join(r["name"] for r in failed) or "height"
            print(f"blocked: {max_rounds} rounds used and these still differ: {names}. Stop fixing; list each with its reason and ask the user")
            return 2
    if bad:
        why = f"{len(failed) + len(outside)} region(s) differ" if failed or outside else f"heights are {height_gap} px apart"
        print(f"RESULT fail: {why}")
        return 1
    print("RESULT pass")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("info", help="say whether a PNG file can be read, and its size")
    p.add_argument("file")
    p = sub.add_parser("compare", help="compare a screenshot with the reference, region by region")
    p.add_argument("reference", help="the mockup or reference screenshot (PNG)")
    p.add_argument("actual", help="the screenshot of the built page at the same width (PNG)")
    p.add_argument("--grid", help="columns x rows, for example 6x8 (default from references/defaults.json)")
    p.add_argument("--regions", help="JSON list of named regions: name, x, y, width, height, optional max_diff, ignore and reason")
    p.add_argument("--tolerance", type=int, help="channel difference (0-255) below which two pixels count as equal")
    p.add_argument("--max-diff", type=float, help="percent of differing pixels a region may have")
    p.add_argument("--diff", help="write a new PNG that marks the differing pixels")
    p.add_argument("--report", help="write the region table to this new JSON file")
    p.add_argument("--record", action="store_true", help="count this comparison as a round in .mstack/ui-match/rounds.json")
    p.add_argument("--root", default=".", help="project folder for --record (default: current folder)")
    args = parser.parse_args()
    return {"info": cmd_info, "compare": cmd_compare}[args.action](args)


if __name__ == "__main__":
    sys.exit(main())

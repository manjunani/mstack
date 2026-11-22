"""Test the PNG reader that sim-proof, sim-flow, ios-a11y-check and ios-submit-check share.

Usage: python3 pngstat_cases.py <new folder under .testrun/>

Part 1 decodes PNG files written by fixtures.py with every row filter and colour type and
compares each decoded pixel with the pixel that was written.
Part 2 runs the command line on real, blank, broken and missing files and checks the exit code.
Part 3 (macOS only) lets `sips` re-encode a picture with Apple's encoder and decodes that file,
so the reader is also tested on a PNG this test did not write.
"""
import importlib.util
import pathlib
import shutil
import subprocess
import sys
import time

import fixtures as fx

W = fx.workdir(sys.argv)
SCRIPT = fx.SKILLS / "sim-proof" / "scripts" / "pngstat.py"
spec = importlib.util.spec_from_file_location("pngstat", SCRIPT)
pngstat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pngstat)
c = fx.Cases("pngstat")
PY = sys.executable


def decoded_pixels(path):
    info, rows, palette, trns = pngstat.decode(pathlib.Path(path).read_bytes())
    channels = pngstat.CHANNELS[info["colour_type"]]
    out = []
    for row in rows:
        if info["depth"] < 8:
            out.append([(v,) for v in pngstat._samples(row, info["width"], info["depth"])])
        elif info["depth"] == 8:
            out.append([tuple(row[i:i + channels]) for i in range(0, len(row), channels)])
        else:
            vals = [int.from_bytes(row[i:i + 2], "big") for i in range(0, len(row), 2)]
            out.append([tuple(vals[i:i + channels]) for i in range(0, len(vals), channels)])
    return out


# Part 1: write, decode, compare every pixel.
rgb = fx.picture(61, 47, seed=3)
for flt in (0, 1, 2, 3, 4, "mixed"):
    p = fx.write_png(W / f"rgb-f{flt}.png", rgb, row_filter=flt)
    c.true(decoded_pixels(p) == rgb, f"RGB 8-bit, row filter {flt}: every pixel decodes to what was written")
rgba = fx.picture(40, 33, seed=5, alpha=200)
p = fx.write_png(W / "rgba.png", rgba, colour_type=6, row_filter="mixed")
c.true(decoded_pixels(p) == rgba, "RGBA 8-bit, mixed filters")
grey = [[((x * y) % 256,) for x in range(37)] for y in range(29)]
p = fx.write_png(W / "grey.png", grey, colour_type=0, row_filter="mixed")
c.true(decoded_pixels(p) == grey, "grey 8-bit, mixed filters")
grey_alpha = [[((x + y) % 256, (x * 5) % 256) for x in range(31)] for y in range(23)]
p = fx.write_png(W / "grey-alpha.png", grey_alpha, colour_type=4, row_filter="mixed")
c.true(decoded_pixels(p) == grey_alpha, "grey with alpha, mixed filters")
deep = [[((x * 997) % 65536, (y * 811) % 65536, (x * y) % 65536) for x in range(25)] for y in range(21)]
p = fx.write_png(W / "rgb16.png", deep, colour_type=2, depth=16, row_filter="mixed")
c.true(decoded_pixels(p) == deep, "RGB 16-bit, mixed filters")
one_bit = [[((x // 3 + y) % 2,) for x in range(43)] for y in range(17)]
p = fx.write_png(W / "grey1.png", one_bit, colour_type=0, depth=1, row_filter="mixed")
c.true(decoded_pixels(p) == one_bit, "grey 1-bit (packed samples), mixed filters")
pal = [(255, 255, 255), (0, 0, 0), (200, 30, 30), (30, 30, 200)]
indexed = [[((x // 4 + y // 3) % 4,) for x in range(50)] for y in range(30)]
p = fx.write_png(W / "pal2.png", indexed, colour_type=3, depth=2, palette=pal, trns=[255, 255, 0], row_filter="mixed")
c.true(decoded_pixels(p) == indexed, "palette 2-bit with transparency chunk, mixed filters")
limits, _ = pngstat.load_limits()
st = pngstat.stats(p, limits, pure=True, band=False)
c.true(st["ok"] and st["distinct"] == 4 and 0.2 < st["transparent_fraction"] < 0.3,
       f"palette statistics: 4 colours and about a quarter transparent (got {st.get('distinct')}, {st.get('transparent_fraction')})")

# Part 2: the command line.
big = W / "screen.png"
fx.write_png(big, fx.picture(400, 860, seed=2), row_filter="mixed")
c.run(0, "a drawn screen is a real picture", [PY, SCRIPT, big])
c.last_line("RESULT pass")
c.has("mstack defaults, not platform facts", "prints that thresholds are not platform facts")
white = fx.write_png(W / "white.png", fx.flat(400, 860))
c.run(1, "an all-white image is blank", [PY, SCRIPT, white])
c.last_line("RESULT fail")
black = fx.write_png(W / "black.png", fx.flat(400, 860, (0, 0, 0)), row_filter=4)
c.run(1, "an all-black image is blank", [PY, SCRIPT, black])
bar_only = fx.flat(400, 860)
for y in range(20, 40):
    for x in range(30, 110):
        bar_only[y][x] = (0, 0, 0)
status = fx.write_png(W / "statusbar-only.png", bar_only)
c.run(1, "white screen with marks only in the status bar is blank", [PY, SCRIPT, status])
c.run(0, "the same file counts as a picture when every row is measured (--whole)", [PY, SCRIPT, status, "--whole"])
clear = fx.write_png(W / "clear.png", [[(10, 200, 30, 0)] * 300 for _ in range(300)], colour_type=6)
c.run(1, "a fully transparent image is blank", [PY, SCRIPT, clear])
c.has("fully transparent")
noise = [[(128 + (x * y) % 2, 128, 128) for x in range(300)] for y in range(300)]
c.run(1, "one-level noise on grey is blank (low brightness spread)", [PY, SCRIPT, fx.write_png(W / "noise.png", noise)])
tiny = fx.write_png(W / "tiny.png", fx.picture(60, 60))
c.run(1, "a 60x60 image is too small to be a screenshot", [PY, SCRIPT, tiny])
cut = W / "cut.png"
cut.write_bytes(big.read_bytes()[:900])
c.run(1, "a file cut short is broken", [PY, SCRIPT, cut])
c.has("cut short")
flipped = bytearray(big.read_bytes())
flipped[60] ^= 0xFF
(W / "badcrc.png").write_bytes(bytes(flipped))
c.run(1, "one changed byte is caught by the chunk checksum", [PY, SCRIPT, W / "badcrc.png"])
c.has("checksum")
(W / "text.png").write_text("this is not an image\n")
c.run(1, "a text file named .png is not a PNG", [PY, SCRIPT, W / "text.png"])
(W / "empty.png").write_bytes(b"")
c.run(1, "an empty file is not a PNG", [PY, SCRIPT, W / "empty.png"])
c.run(2, "a missing file is not verified", [PY, SCRIPT, W / "nope.png"])
c.last_line("RESULT not verified")
c.run(1, "one good and one blank file fail together", [PY, SCRIPT, big, white])
c.has("1 of 2 images")
laced = fx.write_png(W / "interlace-flag.png", fx.picture(300, 300), interlace=1)
c.run(2, "interlaced flag, no sips: cannot be judged", [PY, SCRIPT, laced, "--pure"])
c.run(0, "--help works", [PY, SCRIPT, "--help"])

# Part 3: a phone-sized file, and a file written by Apple's encoder.
phone = W / "phone.png"
fx.write_png(phone, fx.picture(1290, 2796, seed=4), row_filter="mixed")
phone_hash = pngstat.hashlib.sha256(phone.read_bytes()).hexdigest()
phone_white = fx.write_png(W / "phone-white.png", fx.flat(1290, 2796))
if shutil.which("sips"):
    t = time.time()
    c.run(0, "phone-sized picture is judged through a reduced copy", [PY, SCRIPT, phone])
    c.has("reduced copy made by sips")
    print(f"     time with sips: {time.time() - t:.1f}s")
    c.run(1, "phone-sized white image is blank through a reduced copy", [PY, SCRIPT, phone_white])
    apple = W / "apple-encoded.png"
    made = subprocess.run(["sips", "-s", "format", "png", str(W / "rgb-f0.png"), "--out", str(apple)], capture_output=True, text=True)
    if made.returncode == 0 and apple.exists():
        info, rows, _, _ = pngstat.decode(apple.read_bytes())
        channels = pngstat.CHANNELS[info["colour_type"]]
        got = [[tuple(r[i:i + 3]) for i in range(0, len(r), channels)] for r in rows]
        raw = pngstat.zlib.decompress(b"".join(b for k, b in pngstat.read_chunks(apple.read_bytes()) if k == b"IDAT"))
        stride = info["width"] * channels + 1
        used = sorted({raw[y * stride] for y in range(info["height"])})
        filters_note = f"colour type {info['colour_type']}, depth {info['depth']}, row filters used {used}"
        c.true(info["depth"] == 8 and got == rgb, f"a PNG re-encoded by sips ({filters_note}) decodes to the same pixels")
    else:
        print("not run: sips could not re-encode the sample")
    c.true(pngstat.hashlib.sha256(phone.read_bytes()).hexdigest() == phone_hash, "the original file is unchanged after the reduced-copy path")
else:
    print("not run: sips is not on this machine, so the reduced-copy path and the Apple-encoded file were skipped")
t = time.time()
c.run(0, "phone-sized picture, full decode in Python (--pure)", [PY, SCRIPT, phone, "--pure"])
c.has("full decode in Python")
print(f"     time for the full decode: {time.time() - t:.1f}s")

sys.exit(c.finish())

"""Shared helpers for the mstack-apps script tests. Import it; it is not a test by itself.

  write_png(path, pixels, ...)   write a PNG from rows of pixel tuples, with a chosen row filter
  picture(...) / flat(...)       make pixel rows: a screen with drawn blocks, or one flat colour
  Cases                          run a command, compare the exit code and the output text, count results

Every test file takes one argument: a NEW folder under .testrun/ to build its throwaway files in.
"""
import pathlib
import struct
import subprocess
import sys
import zlib

PACK = pathlib.Path(__file__).resolve().parent.parent.parent
SKILLS = PACK / "skills"


def _chunk(kind, body):
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)


def _filter_row(kind, line, prev, bpp):
    out = bytearray(len(line))
    for i, value in enumerate(line):
        a = line[i - bpp] if i >= bpp else 0
        b = prev[i]
        c = prev[i - bpp] if i >= bpp else 0
        if kind == 0:
            pred = 0
        elif kind == 1:
            pred = a
        elif kind == 2:
            pred = b
        elif kind == 3:
            pred = (a + b) >> 1
        else:
            p = a + b - c
            pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
            pred = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
        out[i] = (value - pred) & 255
    return bytes(out)


def write_png(path, pixels, colour_type=2, depth=8, row_filter=0, palette=None, trns=None, interlace=0):
    """pixels: list of rows; each row a list of tuples (one int per channel, or a palette index).

    row_filter: 0 to 4, or "mixed" to cycle through all five.
    """
    height, width = len(pixels), len(pixels[0])
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[colour_type]
    lines = []
    for row in pixels:
        if depth < 8:
            bits = "".join(format(px[0], f"0{depth}b") for px in row)
            bits += "0" * (-len(bits) % 8)
            lines.append(bytes(int(bits[i:i + 8], 2) for i in range(0, len(bits), 8)))
        elif depth == 8:
            lines.append(bytes(v for px in row for v in px))
        else:
            lines.append(b"".join(struct.pack(">H", v) for px in row for v in px))
    bpp = max(1, channels * depth // 8)
    raw, prev = bytearray(), bytes(len(lines[0]))
    for y, line in enumerate(lines):
        kind = y % 5 if row_filter == "mixed" else row_filter
        raw.append(kind)
        raw += _filter_row(kind, line, prev, bpp)
        prev = line
    body = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, colour_type, 0, 0, interlace))
    if palette:
        body += _chunk(b"PLTE", bytes(v for rgb in palette for v in rgb))
    if trns:
        body += _chunk(b"tRNS", bytes(trns))
    body += _chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + _chunk(b"IEND", b"")
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


def flat(width, height, colour=(255, 255, 255)):
    return [[colour] * width for _ in range(height)]


def picture(width, height, background=(250, 250, 250), seed=1, alpha=None):
    """A stand-in for a screen: a title bar, several text-like bars and a coloured button."""
    rows = [[background] * width for _ in range(height)]

    def block(x0, y0, x1, y1, colour):
        for y in range(max(0, y0), min(height, y1)):
            rows[y][max(0, x0):min(width, x1)] = [colour] * (min(width, x1) - max(0, x0))

    block(0, int(height * 0.08), width, int(height * 0.16), (30 + seed * 20 % 200, 90, 160))
    for n in range(6):
        y = int(height * (0.22 + n * 0.09))
        block(int(width * 0.08), y, int(width * (0.5 + 0.06 * ((n + seed) % 5))), y + max(2, height // 60), (40, 40, 48))
    block(int(width * 0.2), int(height * 0.82), int(width * 0.8), int(height * 0.88), (20, 140 + seed * 10 % 100, 90))
    for y in range(int(height * 0.18), int(height * 0.2)):
        for x in range(width):
            rows[y][x] = ((x * 7 + seed) % 256, (x * 3) % 256, 120)
    if alpha is not None:
        rows = [[px + (alpha,) for px in row] for row in rows]
    return rows


class Cases:
    """Run commands and keep score. Each case names the exit code it expects."""

    def __init__(self, title):
        self.title, self.passed, self.failed, self.output = title, 0, 0, ""
        print(f"#### {title}")

    def run(self, want, label, command, cwd=None, env=None, stdin=None):
        done = subprocess.run([str(c) for c in command], capture_output=True, text=True, cwd=cwd, env=env, input=stdin)
        self.output = done.stdout + done.stderr
        last = (done.stdout.strip().splitlines() or [""])[-1]
        good = done.returncode == want
        self._score(good, f"[exit {done.returncode}, expect {want}] {label}", f"last line: {last}")
        return done

    def has(self, text, label=None):
        self._score(text in self.output, f"[text] {label or text}", f"missing: {text}")

    def lacks(self, text, label=None):
        self._score(text not in self.output, f"[no text] {label or text}", f"present: {text}")

    def last_line(self, prefix, label=None):
        last = (self.output.strip().splitlines() or [""])[-1]
        self._score(last.startswith(prefix), f"[last line] {label or prefix}", f"last line was: {last}")

    def true(self, condition, label):
        self._score(bool(condition), f"[check] {label}", "condition is false")

    def _score(self, good, line, detail):
        if good:
            self.passed += 1
            print(f"ok   {line}")
        else:
            self.failed += 1
            print(f"BAD  {line}\n       {detail}")
            for row in self.output.strip().splitlines()[-10:]:
                print(f"       | {row}")

    def finish(self):
        print(f"{self.title}: {self.passed + self.failed} checks, {self.passed} ok, {self.failed} bad")
        return 1 if self.failed else 0


def workdir(argv):
    """The NEW folder given on the command line. Refuses a folder that exists or is outside .testrun."""
    if len(argv) != 2:
        sys.exit("usage: <this file> <new folder under .testrun/>")
    path = pathlib.Path(argv[1]).resolve()
    if ".testrun" not in path.parts:
        sys.exit(f"refusing: {path} is not under a .testrun folder")
    if path.exists():
        sys.exit(f"refusing: {path} already exists; give a new folder name")
    path.mkdir(parents=True)
    return path

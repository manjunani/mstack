#!/usr/bin/env python3
"""Check a diagram file before it ships. Reads the file only; no browser, no renderer.

Formats:
  .svg              every rule below (an exported .drawio.svg is read as SVG)
  .drawio, .xml     draw.io files, plain or compressed pages: every rule except off-canvas
                    (draw.io has no fixed canvas)
  .mmd, .mermaid    Mermaid source: only colours and font sizes set in style and classDef
                    lines, and nodes with an empty label. Layout is made by the renderer, so
                    the layout rules end as not verified: export to SVG and run again.

Rules. Each finding names the element (its id, or tag[n] when it has none) and its
coordinates in the file's own units:
  overlap      two shapes overlap without one holding the other; two labels overlap;
               a label crosses a shape that is not its own
  clipped      a label runs past the edge of the shape it sits in
  off-canvas   a label or shape runs outside the viewBox (or width and height)
  contrast     text on the fill behind it is under the limit (4.5:1, large text 3:1)
  theme        text that passes on a light page fails on a dark one: a hard-coded colour
               on a transparent canvas
  unlabelled   a shape with no text in it or next to it, and no <title> or aria-label
  loose-edge   a line, polyline or unfilled path (or a draw.io edge) whose end touches
               no shape, label or other edge
  small-font   rendered font size under the minimum; with --display-width the SVG is
               scaled to the width it is shown at

Text width is estimated from the number of characters, because there are no font
metrics; tolerances allow for that. Rotated or skewed elements, <use>, <image> and HTML
labels (foreignObject) are listed as not measured. Limits live in
references/limits.json and are marked unverified there.

Exit codes: 0 pass, 1 at least one finding, 2 not verified (something could not be
measured, Mermaid layout, bad input) or blocked (file missing).
"""
import argparse
import base64
import colorsys
import fnmatch
import html
import json
import math
import pathlib
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET
import zlib

HERE = pathlib.Path(__file__).resolve().parent
LIMITS_FILE = HERE.parent / "references" / "limits.json"
NUM_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
THEMES = ("light", "dark")
TRANSPARENT = (0.0, 0.0, 0.0, 0.0)
NAMED = {
    "black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0), "green": (0, 128, 0), "blue": (0, 0, 255),
    "yellow": (255, 255, 0), "gray": (128, 128, 128), "grey": (128, 128, 128), "silver": (192, 192, 192),
    "navy": (0, 0, 128), "teal": (0, 128, 128), "orange": (255, 165, 0), "purple": (128, 0, 128),
    "maroon": (128, 0, 0), "olive": (128, 128, 0), "lime": (0, 255, 0), "aqua": (0, 255, 255), "cyan": (0, 255, 255),
    "fuchsia": (255, 0, 255), "magenta": (255, 0, 255), "darkgray": (169, 169, 169), "darkgrey": (169, 169, 169),
    "lightgray": (211, 211, 211), "lightgrey": (211, 211, 211), "dimgray": (105, 105, 105), "dimgrey": (105, 105, 105),
    "gainsboro": (220, 220, 220), "whitesmoke": (245, 245, 245), "lightblue": (173, 216, 230),
    "steelblue": (70, 130, 180), "darkblue": (0, 0, 139), "darkgreen": (0, 100, 0), "lightgreen": (144, 238, 144),
    "darkred": (139, 0, 0), "pink": (255, 192, 203), "gold": (255, 215, 0), "beige": (245, 245, 220),
    "ivory": (255, 255, 240), "khaki": (240, 230, 140), "lavender": (230, 230, 250), "tomato": (255, 99, 71),
    "coral": (255, 127, 80), "salmon": (250, 128, 114), "skyblue": (135, 206, 235), "slategray": (112, 128, 144),
    "slategrey": (112, 128, 144), "darkslategray": (47, 79, 79), "darkslategrey": (47, 79, 79),
    "lightyellow": (255, 255, 224), "orchid": (218, 112, 214), "indigo": (75, 0, 130), "brown": (165, 42, 42),
    "crimson": (220, 20, 60), "chocolate": (210, 105, 30), "tan": (210, 180, 140), "honeydew": (240, 255, 240),
    "aliceblue": (240, 248, 255), "azure": (240, 255, 255), "mintcream": (245, 255, 250), "snow": (255, 250, 250),
    "linen": (250, 240, 230), "seashell": (255, 245, 238), "lightcyan": (224, 255, 255), "royalblue": (65, 105, 225),
    "dodgerblue": (30, 144, 255), "midnightblue": (25, 25, 112), "darkorange": (255, 140, 0),
    "forestgreen": (34, 139, 34), "seagreen": (46, 139, 87), "firebrick": (178, 34, 34),
}


class InputError(Exception):
    """The file cannot be read as a diagram."""


def nums(text):
    return [float(n) for n in NUM_RE.findall(text or "")]


def local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def fnum(value, default):
    try:
        value = str(value).strip()
        return float(value[:-1]) / 100 if value.endswith("%") else float(value)
    except (TypeError, ValueError):
        return default


def r1(v):
    v = round(v, 1)
    return int(v) if v == int(v) else v


def fmt_box(b):
    return f"({r1(b[0])},{r1(b[1])} {r1(b[2] - b[0])}x{r1(b[3] - b[1])})"


def fmt_pt(p):
    return f"({r1(p[0])},{r1(p[1])})"


# ---------- colour ----------

def split_top(text):
    parts, depth, cur = [], 0, ""
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return [p.strip() for p in parts]


def light_dark(value, theme):
    m = re.fullmatch(r"\s*light-dark\((.*)\)\s*", value or "", re.I | re.S)
    if not m:
        return value
    parts = split_top(m.group(1))
    if len(parts) != 2:
        return value
    return parts[0] if theme == "light" else parts[1]


def parse_colour(value):
    """Return (r, g, b, alpha) with channels 0-255, TRANSPARENT for none, or None when not read."""
    if value is None:
        return None
    v = value.strip().lower()
    if v in ("none", "transparent"):
        return TRANSPARENT
    if v in NAMED:
        return (*NAMED[v], 1.0)
    m = re.fullmatch(r"#([0-9a-f]{3,8})", v)
    if m:
        h = m.group(1)
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h)
        if len(h) not in (6, 8):
            return None
        alpha = int(h[6:8], 16) / 255 if len(h) == 8 else 1.0
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha)
    m = re.fullmatch(r"(rgba?|hsla?)\((.*)\)", v)
    if not m:
        return None
    parts = [p for p in re.split(r"[,\s/]+", m.group(2).strip()) if p]
    if len(parts) not in (3, 4):
        return None
    try:
        alpha = fnum(parts[3], None) if len(parts) == 4 else 1.0
        if alpha is None:
            return None
        if m.group(1).startswith("rgb"):
            ch = [float(p[:-1]) * 2.55 if p.endswith("%") else float(p) for p in parts[:3]]
        else:
            hue = float(parts[0].replace("deg", "")) / 360 % 1
            sat, lig = float(parts[1].rstrip("%")) / 100, float(parts[2].rstrip("%")) / 100
            ch = [c * 255 for c in colorsys.hls_to_rgb(hue, lig, sat)]
    except ValueError:
        return None
    return (*[min(255.0, max(0.0, c)) for c in ch], max(0.0, min(1.0, alpha)))


def luminance(c):
    def lin(x):
        x /= 255
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2])


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def over(top, bottom, alpha):
    return tuple(top[i] * alpha + bottom[i] * (1 - alpha) for i in range(3))


def hexof(c):
    return "#%02x%02x%02x" % tuple(round(x) for x in c[:3])


# ---------- geometry ----------

def inter(a, b):
    return min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])


def inside_box(inner, outer, tol):
    return inner[0] >= outer[0] - tol and inner[1] >= outer[1] - tol and inner[2] <= outer[2] + tol and inner[3] <= outer[3] + tol


def area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def centre(b):
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def point_in(shape, p, tol=0.0):
    ell = shape.get("ell")
    if ell:
        cx, cy, rx, ry = ell
        if rx + tol <= 0 or ry + tol <= 0:
            return False
        return ((p[0] - cx) / (rx + tol)) ** 2 + ((p[1] - cy) / (ry + tol)) ** 2 <= 1
    b = shape["box"]
    return b[0] - tol <= p[0] <= b[2] + tol and b[1] - tol <= p[1] <= b[3] + tol


def hits_box(shape, box, tol):
    """True when the shape and the box share more than tol on both axes."""
    ix, iy = inter(shape["box"], box)
    if ix <= tol or iy <= tol:
        return False
    if not shape.get("ell"):
        return True
    cx, cy, rx, ry = shape["ell"]
    nearest = (min(max(cx, box[0]), box[2]), min(max(cy, box[1]), box[3]))
    return point_in({"ell": (cx, cy, rx - tol, ry - tol)}, nearest)


def dist_to_box(p, b):
    dx = max(b[0] - p[0], 0, p[0] - b[2])
    dy = max(b[1] - p[1], 0, p[1] - b[3])
    return math.hypot(dx, dy)


def dist_to_border(shape, p):
    """Distance from p to the shape's outline, and whether p is inside."""
    ell = shape.get("ell")
    if ell:
        cx, cy, rx, ry = ell
        r = max(min(rx, ry), 1e-9)
        d = math.hypot((p[0] - cx) * r / max(rx, 1e-9), (p[1] - cy) * r / max(ry, 1e-9))
        return abs(d - r), d <= r
    b = shape["box"]
    inside = b[0] <= p[0] <= b[2] and b[1] <= p[1] <= b[3]
    if inside:
        return min(p[0] - b[0], b[2] - p[0], p[1] - b[1], b[3] - p[1]), True
    return dist_to_box(p, b), False


def dist_to_segment(p, a, b):
    vx, vy = b[0] - a[0], b[1] - a[1]
    length = vx * vx + vy * vy
    t = 0.0 if length == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / length))
    return math.hypot(p[0] - a[0] - t * vx, p[1] - a[1] - t * vy)


def mat_mul(m, n):
    a, b, c, d, e, f = m
    a2, b2, c2, d2, e2, f2 = n
    return (a * a2 + c * b2, b * a2 + d * b2, a * c2 + c * d2, b * c2 + d * d2, a * e2 + c * f2 + e, b * e2 + d * f2 + f)


def parse_transform(text):
    m = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    if not text:
        return m
    for name, args in re.findall(r"([a-zA-Z]+)\s*\(([^)]*)\)", text):
        v = nums(args)
        name = name.lower()
        if name == "matrix" and len(v) == 6:
            t = tuple(v)
        elif name == "translate" and v:
            t = (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0)
        elif name == "scale" and v:
            t = (v[0], 0, 0, v[1] if len(v) > 1 else v[0], 0, 0)
        elif name == "rotate" and v:
            r = math.radians(v[0])
            t = (math.cos(r), math.sin(r), -math.sin(r), math.cos(r), 0, 0)
            if len(v) == 3:
                t = mat_mul(mat_mul((1, 0, 0, 1, v[1], v[2]), t), (1, 0, 0, 1, -v[1], -v[2]))
        elif name == "skewx" and v:
            t = (1, 0, math.tan(math.radians(v[0])), 1, 0, 0)
        elif name == "skewy" and v:
            t = (1, math.tan(math.radians(v[0])), 0, 1, 0, 0)
        else:
            return None
        m = mat_mul(m, t)
    return m


def apply(m, p):
    return (m[0] * p[0] + m[2] * p[1] + m[4], m[1] * p[0] + m[3] * p[1] + m[5])


def box_of(points):
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def path_points(d):
    """All points of a path (ends and control points), or None when it does not parse."""
    counts = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}
    tokens = re.findall(r"[MmLlHhVvCcSsQqTtAaZz]|" + NUM_RE.pattern, d or "")
    pts, cx, cy, sx, sy, cmd, i = [], 0.0, 0.0, 0.0, 0.0, None, 0
    while i < len(tokens):
        if tokens[i].isalpha():
            cmd = tokens[i]
            i += 1
            if cmd in "Zz":
                cx, cy = sx, sy
                pts.append((cx, cy))
                continue
        elif cmd is None or cmd in "Zz":
            return None
        upper, rel = cmd.upper(), cmd.islower()
        n = counts[upper]
        args = tokens[i:i + n]
        if len(args) < n or any(a.isalpha() for a in args):
            return None
        v = [float(a) for a in args]
        i += n
        ox, oy = (cx, cy) if rel else (0.0, 0.0)
        if upper == "H":
            cx = v[0] + ox
        elif upper == "V":
            cy = v[0] + oy
        elif upper == "A":
            cx, cy = v[5] + ox, v[6] + oy
        else:
            for k in range(0, n - 2, 2):
                pts.append((v[k] + ox, v[k + 1] + oy))
            cx, cy = v[n - 2] + ox, v[n - 1] + oy
        pts.append((cx, cy))
        if upper == "M":
            sx, sy = cx, cy
            cmd = "l" if rel else "L"
    return pts or None


def text_lines_size(lines, px, L, mono=False, wrap=None):
    cw = (L["mono_char_width_em"] if mono else L["char_width_em"]) * px
    widths = [len(line) * cw for line in lines]
    count = len(lines)
    if wrap and wrap > 0:
        count = sum(max(1, math.ceil(w / wrap)) for w in widths)
        widths = [min(w, wrap) for w in widths]
    return max(widths, default=0.0), count * px * L["line_height_em"]


# ---------- CSS ----------

INHERITED = {"fill", "fill-opacity", "stroke", "stroke-opacity", "font-size", "font-weight", "font-family",
             "text-anchor", "dominant-baseline", "color", "visibility", "font-style"}
PROPS = INHERITED | {"opacity", "display", "alignment-baseline", "background", "background-color"}
COMPOUND = re.compile(r"^([a-zA-Z][\w-]*|\*)?((?:[.#][\w-]+)*)$")


def parse_decls(text):
    out = {}
    for part in (text or "").split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip().lower()] = v.replace("!important", "").strip()
    return out


def parse_selector(sel):
    tokens = sel.replace(">", " > ").split()
    chain, comb = [], " "
    for tok in tokens:
        if tok == ">":
            comb = ">"
            continue
        if tok == ":root":
            comp = (None, None, (), True)
        else:
            m = COMPOUND.match(tok)
            if not m or not tok:
                return None
            tag = None if m.group(1) in (None, "*") else m.group(1)
            ids = re.findall(r"#([\w-]+)", m.group(2))
            classes = tuple(re.findall(r"\.([\w-]+)", m.group(2)))
            if len(ids) > 1:
                return None
            comp = (tag, ids[0] if ids else None, classes, False)
        chain.append((comb, comp))
        comb = " "
    if not chain:
        return None
    spec = (sum(1 for _, c in chain if c[1]), sum(len(c[2]) + c[3] for _, c in chain), sum(1 for _, c in chain if c[0]))
    return chain, spec


class Sheet:
    def __init__(self, css):
        self.rules, self.skipped, self.dark = [], 0, False
        css = re.sub(r"/\*.*?\*/", "", css or "", flags=re.S)
        self.dark = bool(re.search(r"prefers-color-scheme\s*:\s*dark|light-dark\(", css, re.I))
        self._block(css, None)

    def _block(self, text, media):
        i = 0
        while i < len(text):
            j = text.find("{", i)
            if j < 0:
                break
            prelude, depth, k = text[i:j].strip(), 1, j + 1
            while k < len(text) and depth:
                depth += {"{": 1, "}": -1}.get(text[k], 0)
                k += 1
            body = text[j + 1:k - 1]
            low = prelude.lower()
            if low.startswith("@media"):
                inner = "other"
                if "prefers-color-scheme" in low:
                    inner = "dark" if "dark" in low else "light"
                self._block(body, inner if media is None else "other")
            elif not low.startswith("@"):
                decls = parse_decls(body)
                relevant = any(k in PROPS or k.startswith("--") for k in decls)
                for sel in prelude.split(","):
                    parsed = parse_selector(sel.strip())
                    if parsed is None:
                        self.skipped += relevant
                    else:
                        self.rules.append((media, parsed[1], len(self.rules), parsed[0], decls))
            i = k

    def matching(self, el, ancestors, theme):
        hits = [r for r in self.rules if r[0] in (None, theme) and match_chain(r[3], len(r[3]) - 1, el, ancestors)]
        return [r[4] for r in sorted(hits, key=lambda r: (r[1], r[2]))]


def match_comp(comp, el, ancestors):
    tag, ident, classes, root = comp
    if root:
        return not ancestors
    if tag and local(el.tag) != tag:
        return False
    if ident and el.get("id") != ident:
        return False
    have = set((el.get("class") or "").split())
    return all(c in have for c in classes)


def match_chain(chain, idx, el, ancestors):
    if not match_comp(chain[idx][1], el, ancestors):
        return False
    if idx == 0:
        return True
    if chain[idx][0] == ">":
        return bool(ancestors) and match_chain(chain, idx - 1, ancestors[-1], ancestors[:-1])
    return any(match_chain(chain, idx - 1, ancestors[n], ancestors[:n]) for n in range(len(ancestors) - 1, -1, -1))


def resolve(raw, style, theme):
    """Resolve var() and light-dark(); None when a variable has no value."""
    v = raw
    for _ in range(8):
        m = re.search(r"var\(\s*(--[\w-]+)\s*(?:,\s*((?:[^()]|\([^()]*\))*))?\)", v or "")
        if not m:
            break
        rep = style.get(m.group(1))
        if rep is None:
            rep = m.group(2)
        if rep is None:
            return None
        v = v[:m.start()] + rep.strip() + v[m.end():]
    return light_dark(v, theme).strip() if v is not None else None


def font_px(value, parent_px, style, theme):
    v = resolve(value, style, theme)
    if v is None:
        return parent_px
    v = v.strip().lower()
    keywords = {"xx-small": 9, "x-small": 10, "small": 13, "medium": 16, "large": 18, "x-large": 24, "xx-large": 32}
    if v in keywords:
        return float(keywords[v])
    if v == "smaller":
        return parent_px / 1.2
    if v == "larger":
        return parent_px * 1.2
    n = nums(v)
    if not n:
        return parent_px
    if v.endswith("pt"):
        return n[0] * 4 / 3
    if v.endswith("rem"):
        return n[0] * 16
    if v.endswith("em"):
        return n[0] * parent_px
    if v.endswith("%"):
        return n[0] * parent_px / 100
    return n[0]


def compute(el, ancestors, parent, sheet, theme):
    s = {k: v for k, v in parent.items() if k in INHERITED or k.startswith("--")}
    s["_opacity"] = parent.get("_opacity", 1.0)
    s["_fontpx"] = parent.get("_fontpx", 16.0)
    own = {k: el.get(k) for k in PROPS if el.get(k) is not None}
    for decls in sheet.matching(el, ancestors, theme):
        own.update(decls)
    own.update(parse_decls(el.get("style")))
    for k, v in own.items():
        if str(v).strip().lower() != "inherit":
            s[k] = str(v).strip()
    if "opacity" in own:
        s["_opacity"] *= fnum(resolve(own["opacity"], s, theme), 1.0)
    if "font-size" in own:
        s["_fontpx"] = font_px(own["font-size"], parent.get("_fontpx", 16.0), s, theme)
    return s


def paint(style, prop, theme, L):
    """(rgba, None) or (None, reason) for fill or stroke of an SVG element."""
    raw = style.get(prop, "black" if prop == "fill" else "none")
    v = resolve(raw, style, theme)
    if v is None:
        return None, f"{prop} uses a CSS variable with no value"
    if v.lower() == "currentcolor":
        c = style.get("color")
        v = resolve(c, style, theme) if c else L["page_text_" + theme]
        if v is None:
            return None, "color uses a CSS variable with no value"
    if v.lower().startswith("url("):
        return None, f"{prop} is a gradient or pattern"
    col = parse_colour(v)
    if col is None:
        return None, f"{prop} '{v}' is not a colour this script reads"
    alpha = col[3] * fnum(style.get(prop + "-opacity", 1), 1.0) * style.get("_opacity", 1.0)
    return (col[0], col[1], col[2], alpha), None


# ---------- SVG ----------

SKIP_TAGS = {"defs", "marker", "symbol", "clipPath", "mask", "pattern", "linearGradient", "radialGradient",
             "filter", "style", "script", "title", "desc", "metadata"}


class Diagram:
    def __init__(self, kind):
        self.kind, self.items, self.canvas, self.canvas_note = kind, [], None, ""
        self.root_bg = {}
        self.scale = 1.0
        self.not_measured, self.warnings, self.findings = [], [], []


def length(value, ref=None):
    if value is None:
        return None
    v = str(value).strip()
    n = nums(v)
    if not n:
        return None
    if v.endswith("%"):
        return n[0] * ref / 100 if ref else None
    if v.endswith("pt"):
        return n[0] * 4 / 3
    return n[0]


def ignored(el, patterns):
    if not patterns:
        return False
    keys = [el.get("id") or ""] + (el.get("class") or "").split()
    return any(fnmatch.fnmatch(k, p) for k in keys if k for p in patterns)


def load_svg(text, args, L, themes):
    root = ET.fromstring(text)
    if local(root.tag) != "svg":
        raise InputError(f"the root element is <{local(root.tag)}>, not <svg>")
    D = Diagram("svg")
    sheet = Sheet("\n".join(e.text or "" for e in root.iter() if local(e.tag) == "style"))
    if sheet.skipped:
        D.not_measured.append(f"{sheet.skipped} CSS selector(s) with pseudo-classes, attributes or sibling combinators were not applied; colours may differ")
    vb = nums(root.get("viewBox"))
    width, height = length(root.get("width")), length(root.get("height"))
    if len(vb) == 4 and vb[2] > 0 and vb[3] > 0:
        D.canvas = (vb[0], vb[1], vb[0] + vb[2], vb[1] + vb[3])
        D.canvas_note = f"viewBox {r1(vb[0])} {r1(vb[1])} {r1(vb[2])} {r1(vb[3])}"
        if width and not (root.get("width") or "").strip().endswith("%"):
            D.scale = width / vb[2]
    elif width and height:
        D.canvas = (0.0, 0.0, width, height)
        D.canvas_note = f"width {r1(width)} height {r1(height)}"
    else:
        D.canvas_note = "none (no viewBox, width or height): off-canvas not checked"
        D.not_measured.append("canvas size unknown: off-canvas not checked")
    if args.display_width:
        if D.canvas:
            D.scale = args.display_width / (D.canvas[2] - D.canvas[0])
        else:
            D.warnings.append("--display-width ignored: the SVG has no canvas size")
    if not (root.get("aria-label") or root.get("aria-labelledby") or any(local(c.tag) == "title" and (c.text or "").strip() for c in root)):
        D.warnings.append("no <title> or aria-label on the <svg>: screen readers get no name for the diagram")
    cw = (D.canvas[2] - D.canvas[0]) if D.canvas else None
    ch = (D.canvas[3] - D.canvas[1]) if D.canvas else None
    counter, uses, order = {}, [], [0]
    base = {th: {} for th in themes}
    root_styles = {th: compute(root, [], base[th], sheet, th) for th in themes}
    for th in themes:
        bg = root_styles[th].get("background-color") or root_styles[th].get("background")
        if bg:
            col = parse_colour(resolve(bg, root_styles[th], th) or "")
            if col and col[3] >= 0.999:
                D.root_bg[th] = col[:3]

    def name_of(el, tag, ancestors=()):
        counter[tag] = counter.get(tag, 0) + 1
        if el.get("id"):
            return f"{tag}#{el.get('id')}"
        owner = next((a for a in reversed(ancestors[1:]) if a.get("id")), None)
        return f"{tag}[{counter[tag]}]" + (f" in {local(owner.tag)}#{owner.get('id')}" if owner is not None else "")

    def titled(el):
        return bool(el.get("aria-label") or any(local(c.tag) == "title" and (c.text or "").strip() for c in el))

    def add(item):
        order[0] += 1
        item["order"] = order[0]
        D.items.append(item)

    def walk(el, ancestors, matrix, styles, node):
        tag = local(el.tag)
        if tag in SKIP_TAGS or ignored(el, args.ignore):
            return
        st = {th: compute(el, ancestors, styles[th], sheet, th) for th in themes} if ancestors else styles
        s0 = st[themes[0]]
        if s0.get("display") == "none" or s0.get("visibility") in ("hidden", "collapse"):
            return
        t = parse_transform(el.get("transform"))
        if t is None:
            D.not_measured.append(f"{name_of(el, tag, ancestors)}: transform '{el.get('transform')}' not read")
            return
        m = mat_mul(matrix, t)
        if tag == "svg" and ancestors:
            m = mat_mul(m, (1, 0, 0, 1, length(el.get("x")) or 0, length(el.get("y")) or 0))
        if tag in ("svg", "g", "a", "switch"):
            kids = list(el)
            if tag == "switch":
                texts = [c for c in kids if local(c.tag) == "text"]
                kids = texts[:1] or kids[:1]
            here = node
            if tag == "g" and ancestors:
                here = (id(el), titled(el))
            for child in kids:
                walk(child, ancestors + [el], m, st, here)
            return
        if tag in ("use", "image"):
            uses.append(tag)
            return
        if tag not in ("rect", "circle", "ellipse", "polygon", "polyline", "line", "path", "text", "foreignObject"):
            return
        name = name_of(el, tag, ancestors)
        rotated = abs(m[1]) > 1e-6 or abs(m[2]) > 1e-6
        if rotated:
            D.not_measured.append(f"{name}: rotated or skewed; geometry not checked")
            return
        fills = {th: paint(st[th], "fill", th, L) for th in themes}
        strokes = {th: paint(st[th], "stroke", th, L) for th in themes}
        f0 = fills[themes[0]][0]
        no_fill = f0 is not None and f0[3] <= 0
        s_col = strokes[themes[0]][0]
        has_stroke = s_col is None or s_col[3] > 0
        shape = {"kind": "shape", "name": name, "node": node, "fill": fills, "titled": titled(el) or bool(node and node[1]), "ell": None}
        if tag == "rect":
            x, y = length(el.get("x"), cw) or 0, length(el.get("y"), ch) or 0
            w, h = length(el.get("width"), cw), length(el.get("height"), ch)
            if not w or not h or w <= 0 or h <= 0:
                return
            shape["box"] = box_of([apply(m, (x, y)), apply(m, (x + w, y + h))])
            add(shape)
        elif tag in ("circle", "ellipse"):
            cx, cy = length(el.get("cx"), cw) or 0, length(el.get("cy"), ch) or 0
            if tag == "circle":
                rx = ry = length(el.get("r"), cw) or 0
            else:
                rx, ry = length(el.get("rx"), cw) or 0, length(el.get("ry"), ch) or 0
            if rx <= 0 or ry <= 0:
                return
            c = apply(m, (cx, cy))
            rx, ry = rx * abs(m[0]), ry * abs(m[3])
            shape["ell"] = (c[0], c[1], rx, ry)
            shape["box"] = (c[0] - rx, c[1] - ry, c[0] + rx, c[1] + ry)
            add(shape)
        elif tag in ("polygon", "polyline", "line", "path"):
            if tag == "line":
                raw = [(length(el.get("x1"), cw) or 0, length(el.get("y1"), ch) or 0), (length(el.get("x2"), cw) or 0, length(el.get("y2"), ch) or 0)]
                closed = False
            elif tag == "path":
                raw = path_points(el.get("d"))
                if raw is None:
                    D.not_measured.append(f"{name}: path data not read")
                    return
                closed = "z" in (el.get("d") or "").lower()
            else:
                v = nums(el.get("points"))
                raw = list(zip(v[0::2], v[1::2]))
                closed = tag == "polygon"
                if len(raw) < 2:
                    return
            pts = [apply(m, p) for p in raw]
            if tag == "line" or (no_fill and not closed):
                if has_stroke:
                    add({"kind": "edge", "name": name, "pts": pts, "ends": [("start", pts[0], False, None), ("end", pts[-1], False, None)]})
                return
            shape["box"] = box_of(pts)
            add(shape)
        elif tag == "text":
            add_text(el, name, st, m, node)
        elif tag == "foreignObject":
            x, y = length(el.get("x"), cw) or 0, length(el.get("y"), ch) or 0
            w, h = length(el.get("width"), cw) or 0, length(el.get("height"), ch) or 0
            words = " ".join("".join(el.itertext()).split())
            if w > 1 and h > 1 and words:
                add({"kind": "text", "name": f'{name} "{words[:30]}"', "box": box_of([apply(m, (x, y)), apply(m, (x + w, y + h))]),
                     "node": node, "fg": None, "px": None, "bold": False, "fo": True})
                D.not_measured.append(f"{name}: HTML label; box checked, font size and contrast not measured")
            elif words:
                D.not_measured.append(f"{name}: HTML label without a usable size; not checked")

    def add_text(el, name, st, m, node):
        s0 = st[themes[0]]
        px0 = s0.get("_fontpx", 16.0)
        x0 = (nums(el.get("x")) or [0.0])[0]
        y0 = (nums(el.get("y")) or [0.0])[0]
        x0 += (nums(el.get("dx")) or [0.0])[0]
        y0 += (nums(el.get("dy")) or [0.0])[0]
        lines = [[x0, y0, (el.text or "")]]
        for span in el:
            if local(span.tag) != "tspan":
                continue
            content = "".join(span.itertext())
            sx = (nums(span.get("x")) or [None])[0]
            sy = (nums(span.get("y")) or [None])[0]
            dy = (nums(span.get("dy")) or [0.0])[0]
            if sy is not None or dy:
                lines.append([sx if sx is not None else lines[-1][0], (sy if sy is not None else lines[-1][1]) + dy, content])
            else:
                if sx is not None:
                    lines[-1][0] = sx
                lines[-1][2] += content
            lines[-1][2] += span.tail or ""
        lines = [(lx, ly, " ".join(txt.split())) for lx, ly, txt in lines if txt.strip()]
        if not lines:
            return
        words = " / ".join(t for _, _, t in lines)
        anchor = s0.get("text-anchor", "start")
        baseline = (s0.get("dominant-baseline") or s0.get("alignment-baseline") or "auto").lower()
        mono = "mono" in (s0.get("font-family") or "").lower() or "courier" in (s0.get("font-family") or "").lower()
        boxes = []
        length_attr = length(el.get("textLength"))
        for lx, ly, txt in lines:
            w, _ = text_lines_size([txt], px0, L, mono)
            if length_attr and len(lines) == 1:
                w = length_attr
            left = lx - (w / 2 if anchor == "middle" else w if anchor == "end" else 0)
            if baseline in ("middle", "central"):
                top = ly - px0 / 2
            elif baseline in ("hanging", "text-before-edge", "text-top"):
                top = ly
            elif baseline in ("text-after-edge", "ideographic", "text-bottom"):
                top = ly - px0
            else:
                top = ly - L["ascent_em"] * px0
            boxes.append((left, top, left + w, top + px0))
        corners = [apply(m, (b[0], b[1])) for b in boxes] + [apply(m, (b[2], b[3])) for b in boxes]
        weight = s0.get("font-weight", "normal").lower()
        bold = weight in ("bold", "bolder") or fnum(weight, 400) >= 700
        scale = math.sqrt(abs(m[0] * m[3] - m[1] * m[2]))
        fg = {th: paint(st[th], "fill", th, L) for th in themes}
        add({"kind": "text", "name": f'{name} "{words[:40]}"', "box": box_of(corners), "node": node, "fg": fg,
             "px": px0 * scale * D.scale, "bold": bold, "fo": False})

    for child in root:
        walk(child, [root], (1.0, 0.0, 0.0, 1.0, 0.0, 0.0), root_styles, None)
    if uses:
        D.not_measured.append(f"{len(uses)} <use>/<image> element(s) not checked")
    counts = {}
    for it in D.items:
        if it["kind"] == "shape" and it.get("node"):
            counts[it["node"]] = counts.get(it["node"], 0) + 1
    for it in D.items:
        node = it.get("node")
        if node and counts.get(node, 0) > L["node_group_max_shapes"]:
            it["node"] = None
    return D


# ---------- draw.io ----------

def drawio_pages(text):
    root = ET.fromstring(text)
    tag = local(root.tag)
    if tag == "mxGraphModel":
        return [("page 1", root)]
    if tag != "mxfile":
        raise InputError(f"the root element is <{tag}>, not <mxfile> or <mxGraphModel>")
    pages = []
    for n, d in enumerate(root.findall("diagram"), 1):
        name = d.get("name") or f"page {n}"
        model = d.find("mxGraphModel")
        if model is None:
            raw = (d.text or "").strip()
            if not raw:
                continue
            try:
                data = zlib.decompress(base64.b64decode(raw), -15).decode("utf-8")
                model = ET.fromstring(urllib.parse.unquote(data))
            except (ValueError, zlib.error, ET.ParseError, UnicodeDecodeError):
                raise InputError(f"page '{name}' is compressed in a form this script cannot read")
        pages.append((name, model))
    if not pages:
        raise InputError("the draw.io file has no diagram pages")
    return pages


def parse_style(text):
    out, bare = {}, set()
    for part in (text or "").split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
        else:
            bare.add(part)
    return out, bare


def label_text(value, style):
    v = value or ""
    if style.get("html") == "1":
        v = re.sub(r"<br\s*/?>|</div>|</p>|</li>", "\n", v, flags=re.I)
        v = re.sub(r"<[^>]+>", "", v)
        v = html.unescape(v)
    lines = [" ".join(line.split()) for line in v.split("\n")]
    return [line for line in lines if line]


def drawio_colour(style, key, theme, adaptive, L):
    v = style.get(key)
    if v is None or v.lower() == "default":
        return adaptive, None
    v = light_dark(v, theme)
    col = parse_colour(v)
    if col is None:
        return None, f"{key} '{v}' is not a colour this script reads"
    return col, None


def load_drawio_page(model, args, L, themes):
    D = Diagram("drawio")
    D.canvas_note = "none (draw.io has no fixed canvas): off-canvas not checked"
    root = model.find("root")
    if root is None:
        raise InputError("a page has no <root> element")
    cells = {}
    for n, child in enumerate(root):
        t = local(child.tag)
        if t == "mxCell":
            cell, cid, value = child, child.get("id"), child.get("value")
        elif t in ("object", "UserObject"):
            cell, cid, value = child.find("mxCell"), child.get("id"), child.get("label")
            if cell is None:
                continue
        else:
            continue
        style, bare = parse_style(cell.get("style"))
        geo = cell.find("mxGeometry")
        g = {k: fnum(geo.get(k), 0.0) if geo is not None else 0.0 for k in ("x", "y", "width", "height")}
        points = {}
        if geo is not None:
            for p in geo.findall("mxPoint"):
                if p.get("as"):
                    points[p.get("as")] = (fnum(p.get("x"), 0.0), fnum(p.get("y"), 0.0))
        cells[cid] = {"id": cid, "value": value, "style": style, "bare": bare, "vertex": cell.get("vertex") == "1",
                      "edge": cell.get("edge") == "1", "parent": cell.get("parent"), "source": cell.get("source"),
                      "target": cell.get("target"), "g": g, "points": points, "order": n * 2,
                      "relative": geo is not None and geo.get("relative") == "1"}
    memo = {}

    def offset(cid):
        if cid not in cells or not cells[cid]["vertex"]:
            return (0.0, 0.0)
        if cid not in memo:
            c = cells[cid]
            px, py = offset(c["parent"])
            memo[cid] = (px + c["g"]["x"], py + c["g"]["y"])
        return memo[cid]

    def pat(c, text):
        return any(fnmatch.fnmatch(k, p) for k in (c["id"] or "", text) if k for p in (args.ignore or []))

    shapes_by_id = {}
    for cid, c in cells.items():
        if not c["vertex"]:
            continue
        style, bare = c["style"], c["bare"]
        lines = label_text(c["value"], style)
        if pat(c, " ".join(lines)):
            continue
        name = f"cell#{cid}" + (f' "{" / ".join(lines)[:40]}"' if lines else "")
        px = fnum(style.get("fontSize"), L["drawio_font_px"])
        bold = int(fnum(style.get("fontStyle"), 0)) & 1 == 1
        opacity = fnum(style.get("opacity"), 100) / 100
        text_alpha = fnum(style.get("textOpacity"), 100) / 100 * opacity
        fg = {}
        for th in themes:
            col, why = drawio_colour(style, "fontColor", th, parse_colour(L["page_text_" + th]), L)
            fg[th] = ((col[0], col[1], col[2], col[3] * text_alpha), None) if col else (None, why)
        parent = cells.get(c["parent"])
        if parent and parent["edge"]:
            if lines:
                bgs = {}
                for th in themes:
                    col, why = drawio_colour(style, "labelBackgroundColor", th, TRANSPARENT, L)
                    bgs[th] = col
                D.items.append({"kind": "text", "name": name, "box": None, "node": None, "fg": fg, "px": px, "bold": bold,
                                "fo": False, "order": c["order"] + 1, "bg": bgs})
            continue
        if "group" in bare:
            continue
        ox, oy = offset(c["parent"])
        x, y, w, h = ox + c["g"]["x"], oy + c["g"]["y"], c["g"]["width"], c["g"]["height"]
        box = (x, y, x + w, y + h)
        is_text = "text" in bare or style.get("shape") == "text" or "edgeLabel" in bare
        fills = {}
        for th in themes:
            adaptive = TRANSPARENT if is_text else (*parse_colour(L["page_" + th])[:3], 1.0)
            col, why = drawio_colour(style, "fillColor", th, adaptive, L)
            if style.get("gradientColor") not in (None, "none", ""):
                col, why = None, "gradient fill"
            fills[th] = ((col[0], col[1], col[2], col[3] * opacity * fnum(style.get("fillOpacity"), 100) / 100), None) if col else (None, why)
        ell = None
        if "ellipse" in bare or style.get("shape") in ("ellipse", "doubleEllipse"):
            ell = (x + w / 2, y + h / 2, w / 2, h / 2)
        shape = {"kind": "shape", "name": name, "box": box, "ell": ell, "node": None, "fill": fills, "titled": bool(lines),
                 "order": c["order"], "paint_only": is_text, "cell": cid}
        if w > 0 and h > 0:
            D.items.append(shape)
            shapes_by_id[cid] = shape
        if not lines:
            continue
        hpos, vpos = style.get("labelPosition", "center"), style.get("verticalLabelPosition", "middle")
        wrap = (w - 4) if style.get("whiteSpace") == "wrap" else None
        tw, th_ = text_lines_size(lines, px, L, "mono" in style.get("fontFamily", "").lower(), wrap)
        align, valign = style.get("align", "center"), style.get("verticalAlign", "middle")
        if hpos == "left":
            left = x - tw
        elif hpos == "right":
            left = x + w
        else:
            left = x + (w - tw) / 2 if align == "center" else x + 2 if align == "left" else x + w - 2 - tw
        if vpos == "top":
            top = y - th_
        elif vpos == "bottom":
            top = y + h
        else:
            top = y + (h - th_) / 2 if valign == "middle" else y + 2 if valign == "top" else y + h - 2 - th_
        inside = hpos == "center" and vpos == "middle"
        D.items.append({"kind": "text", "name": name, "box": (left, top, left + tw, top + th_), "node": None, "fg": fg,
                        "px": px, "bold": bold, "fo": False, "order": c["order"] + 1,
                        "owner": shape if (inside and not is_text and w > 0) else None, "clip": inside and not is_text})
    for cid, c in cells.items():
        if not c["edge"]:
            continue
        lines = label_text(c["value"], c["style"])
        if pat(c, " ".join(lines)):
            continue
        name = f"edge#{cid}" + (f' "{" / ".join(lines)[:40]}"' if lines else "")
        ox, oy = offset(c["parent"])
        ends = []
        for which, attr, key in (("source", c["source"], "sourcePoint"), ("target", c["target"], "targetPoint")):
            p = c["points"].get(key)
            p = (p[0] + ox, p[1] + oy) if p else None
            if attr:
                if attr in cells:
                    ends.append((which, p, True, None))
                else:
                    ends.append((which, p, False, f"its {which} refers to cell '{attr}', which does not exist"))
            else:
                ends.append((which, p, False, None if p else f"has no {which} cell and no {which} point"))
        D.items.append({"kind": "edge", "name": name, "pts": [e[1] for e in ends if e[1]], "ends": ends, "order": c["order"]})
        if lines:
            fg, bgs = {}, {}
            for th in themes:
                col, why = drawio_colour(c["style"], "fontColor", th, parse_colour(L["page_text_" + th]), L)
                fg[th] = (col, None) if col else (None, why)
                bgs[th] = drawio_colour(c["style"], "labelBackgroundColor", th, TRANSPARENT, L)[0]
            D.items.append({"kind": "text", "name": name, "box": None, "node": None, "fg": fg,
                            "px": fnum(c["style"].get("fontSize"), L["drawio_font_px"]),
                            "bold": int(fnum(c["style"].get("fontStyle"), 0)) & 1 == 1, "fo": False,
                            "order": c["order"] + 1, "bg": bgs})
    return D


# ---------- checks shared by SVG and draw.io ----------

def check(D, L, themes, min_font):
    tol = L["overlap_tolerance_px"]
    shapes = [i for i in D.items if i["kind"] == "shape"]
    texts = [i for i in D.items if i["kind"] == "text"]
    edges = [i for i in D.items if i["kind"] == "edge"]
    boxes = [i["box"] for i in shapes + texts if i.get("box")]
    frame = D.canvas or (box_of([(b[0], b[1]) for b in boxes] + [(b[2], b[3]) for b in boxes]) if boxes else None)
    F = D.findings
    for s in shapes:
        s["bg"] = bool(frame) and D.kind == "svg" and area(s["box"]) >= L["background_cover"] * area(frame) and \
            inter(s["box"], frame)[0] * inter(s["box"], frame)[1] >= L["background_cover"] * area(frame)
    real = [s for s in shapes if not s["bg"] and not s.get("paint_only")
            and max(s["box"][2] - s["box"][0], s["box"][3] - s["box"][1]) >= L["min_node_px"]]

    def same_node(a, b):
        return a.get("node") is not None and a.get("node") == b.get("node")

    # where each label sits
    for t in texts:
        if not t.get("box"):
            continue
        c = centre(t["box"])
        if "owner" not in t:
            holders = [s for s in real if point_in(s, c)]
            t["owner"] = min(holders, key=lambda s: area(s["box"])) if holders else None
            t["clip"] = True
    labelled = set()
    for t in texts:
        if not t.get("box"):
            continue
        c = centre(t["box"])
        for s in real:
            if point_in(s, c) or same_node(s, t):
                labelled.add(id(s))
        if t.get("owner") is None and not any(point_in(s, c) for s in real):
            near = [s for s in real if dist_to_box(c, s["box"]) <= L["label_gap_px"] + (t["box"][3] - t["box"][1]) / 2]
            for s in near:
                labelled.add(id(s))

    # overlap: shapes
    for i, a in enumerate(real):
        for b in real[i + 1:]:
            if same_node(a, b):
                continue
            ix, iy = inter(a["box"], b["box"])
            if ix <= tol or iy <= tol or inside_box(a["box"], b["box"], tol) or inside_box(b["box"], a["box"], tol):
                continue
            if a.get("ell") and b.get("ell"):
                (ax, ay, arx, ary), (bx, by, brx, bry) = a["ell"], b["ell"]
                gap = math.hypot(ax - bx, ay - by)
                ang = math.atan2(by - ay, bx - ax)
                ra = math.hypot(arx * math.cos(ang), ary * math.sin(ang))
                rb = math.hypot(brx * math.cos(ang), bry * math.sin(ang))
                if gap >= ra + rb - tol:
                    continue
            elif a.get("ell") and not hits_box(a, b["box"], tol):
                continue
            elif b.get("ell") and not hits_box(b, a["box"], tol):
                continue
            F.append(("overlap", f"{a['name']} at {fmt_box(a['box'])} and {b['name']} at {fmt_box(b['box'])} overlap by {r1(ix)}x{r1(iy)}"))
    # overlap: labels
    boxed = [t for t in texts if t.get("box")]
    for i, a in enumerate(boxed):
        for b in boxed[i + 1:]:
            ix, iy = inter(a["box"], b["box"])
            if ix > tol and iy > tol:
                F.append(("overlap", f"label {a['name']} at {fmt_box(a['box'])} and label {b['name']} at {fmt_box(b['box'])} overlap by {r1(ix)}x{r1(iy)}"))
    # overlap: label across a shape that is not its own
    for t in boxed:
        c = centre(t["box"])
        for s in real:
            if s is t.get("owner") or point_in(s, c) or same_node(s, t):
                continue
            if hits_box(s, t["box"], tol):
                F.append(("overlap", f"label {t['name']} at {fmt_box(t['box'])} crosses {s['name']} at {fmt_box(s['box'])}"))
    # clipped
    for t in boxed:
        own = t.get("owner")
        if own is None or not t.get("clip"):
            continue
        b, o = t["box"], own["box"]
        if own.get("ell"):
            cx, cy, rx, ry = own["ell"]
            tx, ty = centre(b)
            ax = rx * math.sqrt(max(0.0, 1 - ((ty - cy) / ry) ** 2)) if ry else 0
            ay = ry * math.sqrt(max(0.0, 1 - ((tx - cx) / rx) ** 2)) if rx else 0
            past = max(b[2] - (cx + ax), (cx - ax) - b[0], b[3] - (cy + ay), (cy - ay) - b[1])
        else:
            past = max(o[0] - b[0], b[2] - o[2], o[1] - b[1], b[3] - o[3])
        if past > tol:
            F.append(("clipped", f"label {t['name']} at {fmt_box(b)} runs {r1(past)}px past the edge of {own['name']} at {fmt_box(o)}"))
    # off-canvas
    if D.canvas:
        cv = D.canvas
        for it in boxed + [s for s in shapes if not s["bg"]]:
            b = it["box"]
            sides = {"left": cv[0] - b[0], "top": cv[1] - b[1], "right": b[2] - cv[2], "bottom": b[3] - cv[3]}
            worst = max(sides, key=sides.get)
            if sides[worst] > tol:
                kind = "label " if it["kind"] == "text" else ""
                F.append(("off-canvas", f"{kind}{it['name']} at {fmt_box(b)} runs {r1(sides[worst])}px past the {worst} edge of the canvas {fmt_box(cv)}"))
    # unlabelled
    for s in real:
        if id(s) not in labelled and not s.get("titled"):
            F.append(("unlabelled", f"{s['name']} at {fmt_box(s['box'])} has no text in it or within {r1(L['label_gap_px'])}px, and no <title> or aria-label"))
    # loose edges
    gap = L["edge_gap_px"]
    leaves = [s for s in real if not any(o is not s and not same_node(o, s) and inside_box(o["box"], s["box"], 0) for o in real)]
    for e in edges:
        for which, p, attached, problem in e["ends"]:
            if attached:
                continue
            if p is None:
                F.append(("loose-edge", f"edge {e['name']} {problem}"))
                continue
            ok = False
            for s in real:
                d, inside = dist_to_border(s, p)
                if d <= gap or (inside and any(s is leaf for leaf in leaves)):
                    ok = True
                    break
            ok = ok or any(dist_to_box(p, t["box"]) <= gap for t in boxed)
            if not ok:
                for o in edges:
                    if o is e:
                        continue
                    pts = o["pts"]
                    if any(dist_to_segment(p, pts[k], pts[k + 1]) <= gap for k in range(len(pts) - 1)) or any(math.hypot(p[0] - q[0], p[1] - q[1]) <= gap for q in pts):
                        ok = True
                        break
            if not ok:
                near = min(real, key=lambda s: dist_to_border(s, p)[0], default=None)
                hint = f" (nearest: {near['name']}, {r1(dist_to_border(near, p)[0])}px away)" if near else ""
                extra = f"; {problem}" if problem else ""
                F.append(("loose-edge", f"edge {e['name']} {which} at {fmt_pt(p)} touches no shape, label or edge{hint}{extra}"))
    # small font
    for t in texts:
        if t.get("px") is not None and t["px"] < min_font - 0.05:
            where = f" at {fmt_box(t['box'])}" if t.get("box") else ""
            F.append(("small-font", f"label {t['name']}{where} is {r1(t['px'])}px; the minimum is {r1(min_font)}px"))
    # contrast and theme
    painters = sorted(shapes, key=lambda s: s["order"])
    for t in texts:
        if t.get("fg") is None:
            continue
        results = {}
        for th in themes:
            col, why = t["fg"][th]
            if col is None:
                D.not_measured.append(f"{t['name']}: contrast not measured ({why})")
                break
            if col[3] <= 0:
                break
            bg, why = background(t, painters, th, D, L)
            if bg is None:
                D.not_measured.append(f"{t['name']}: contrast not measured ({why})")
                break
            fg = over(col, bg, min(1.0, col[3]))
            large = t["px"] is not None and (t["px"] >= L["large_text_px"] or (t["bold"] and t["px"] >= L["large_bold_text_px"]))
            need = L["contrast_large_min"] if large else L["contrast_text_min"]
            results[th] = (contrast(fg, bg), need, hexof(fg), hexof(bg))
        else:
            where = f" at {fmt_box(t['box'])}" if t.get("box") else ""
            light = results.get("light")
            for th, (ratio, need, fg, bg) in results.items():
                if ratio >= need:
                    continue
                if th == "dark" and light and light[0] < light[1] and (light[2], light[3]) == (fg, bg):
                    continue
                tag = f" in the {th} theme" if len(themes) > 1 else ""
                rule = "theme" if th == "dark" and light and light[0] >= light[1] else "contrast"
                F.append((rule, f"label {t['name']}{where}: {fg} on {bg} is {ratio:.2f}:1{tag}; needs {need}:1"))


def background(t, painters, theme, D, L):
    if t.get("bg") is not None:
        col = t["bg"].get(theme)
        base = D.root_bg.get(theme) or parse_colour(L["page_" + theme])[:3]
        if col is None:
            return None, "label background colour not read"
        return (over(col, base, col[3]) if col[3] > 0 else base), None
    c = centre(t["box"])
    layers, base = [], None
    for s in reversed(painters):
        if s["order"] >= t["order"] or not point_in(s, c):
            continue
        col, why = s["fill"][theme]
        if col is None:
            return None, f"{s['name']}: {why}"
        if col[3] <= 0:
            continue
        if col[3] >= 0.999:
            base = col[:3]
            break
        layers.append(col)
    if base is None:
        base = D.root_bg.get(theme) or parse_colour(L["page_" + theme])[:3]
    for col in reversed(layers):
        base = over(col, base, col[3])
    return base, None


# ---------- Mermaid ----------

def check_mermaid(text, L, themes, min_font):
    findings, notes = [], []
    init_theme = None
    m = re.search(r"%%\{\s*init\s*:(.*?)\}%%", text, re.S)
    if m:
        t = re.search(r"['\"]?theme['\"]?\s*:\s*['\"](\w+)['\"]", m.group(1))
        init_theme = t.group(1).lower() if t else None
    fixed = None if init_theme is None else ("dark" if init_theme == "dark" else "light")
    check_themes = [fixed] if fixed else list(themes)
    styled = 0
    for n, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        sm = re.match(r"^(style|classDef)\s+(\S+)\s+(.+?);?\s*$", s)
        if sm:
            styled += 1
            props = {}
            for part in split_top(sm.group(3)):
                if ":" in part:
                    k, v = part.split(":", 1)
                    props[k.strip().lower()] = v.strip()
            what = f"{'node' if sm.group(1) == 'style' else 'class'} {sm.group(2)} (line {n})"
            px = font_px(props["font-size"], 16.0, {}, "light") if "font-size" in props else None
            if px is not None and px < min_font - 0.05:
                findings.append(("small-font", f"{what}: font-size {r1(px)}px; the minimum is {r1(min_font)}px"))
            fill, colour = props.get("fill"), props.get("color")
            if not fill and not colour:
                continue
            large = px is not None and px >= L["large_text_px"]
            need = L["contrast_large_min"] if large else L["contrast_text_min"]
            light_fail = None
            for th in check_themes:
                f = parse_colour(fill) if fill else parse_colour(L["mermaid_fill_" + th])
                c = parse_colour(colour) if colour else parse_colour(L["mermaid_text_" + th])
                if f is None or c is None:
                    notes.append(f"{what}: colour not read")
                    break
                base = parse_colour(L["page_" + th])[:3]
                bg = over(f, base, f[3])
                fg = over(c, bg, c[3])
                ratio = contrast(fg, bg)
                ok = ratio >= need
                if th == "light":
                    light_fail = not ok
                if not ok and not (th == "dark" and light_fail):
                    source = "" if fill and colour else " (the other colour comes from the Mermaid theme)"
                    rule = "theme" if th == "dark" and light_fail is False else "contrast"
                    tag = f" in the {th} theme" if len(check_themes) > 1 else ""
                    findings.append((rule, f"{what}: {hexof(fg)} on {hexof(bg)} is {ratio:.2f}:1{tag}; needs {need}:1{source}"))
        for em in re.finditer(r"(?<![\w-])([A-Za-z_][\w-]*)\s*(\[\s*\]|\(\s*\)|\{\s*\}|\[\s*\"\s*\"\s*\]|\(\(\s*\)\))", s):
            findings.append(("unlabelled", f"node {em.group(1)} (line {n}) has an empty label"))
    return findings, notes, styled, init_theme


# ---------- main ----------

def load_limits():
    data = json.loads(LIMITS_FILE.read_text(encoding="utf-8"))
    values = {k: v["value"] for k, v in data.items() if isinstance(v, dict) and "value" in v}
    unverified = sorted(k for k, v in data.items() if isinstance(v, dict) and not v.get("verified"))
    return values, unverified


def report(findings, not_measured, warnings, summary):
    by_rule = {}
    for rule, msg in findings:
        by_rule[rule] = by_rule.get(rule, 0) + 1
        print(f"FAIL {rule:<11} {msg}")
    seen = set()
    for line in not_measured:
        if line not in seen:
            seen.add(line)
            print(f"not measured: {line}")
    for line in warnings:
        print(f"warning: {line}")
    if findings:
        parts = ", ".join(f"{n} {r}" for r, n in sorted(by_rule.items()))
        print(f"RESULT fail: {len(findings)} finding(s): {parts}")
        return 1
    if seen:
        print(f"RESULT not verified: {len(seen)} item(s) could not be measured (see 'not measured' lines)")
        return 2
    print(f"RESULT pass: {summary}")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", help="diagram file: .svg, .drawio (or draw.io .xml), .mmd")
    parser.add_argument("--format", choices=["auto", "svg", "drawio", "mermaid"], default="auto", help="override the format taken from the file name")
    parser.add_argument("--theme", choices=["both", "light", "dark"], default="both", help="page theme(s) the diagram is shown on (default both)")
    parser.add_argument("--display-width", type=float, help="width in px the SVG is shown at; font sizes are scaled to it")
    parser.add_argument("--min-font", type=float, help="minimum font size in px (default from references/limits.json)")
    parser.add_argument("--ignore", action="append", default=[], metavar="PATTERN", help="skip elements whose id or class (draw.io: id or label) matches this glob; repeatable")
    args = parser.parse_args()

    path = pathlib.Path(args.file)
    if not path.is_file():
        print(f"file not found: {path}")
        print(f"blocked: file not found: {path}; give the path to the diagram")
        return 2
    try:
        L, unverified = load_limits()
    except (OSError, ValueError, KeyError) as exc:
        print(f"blocked: references/limits.json could not be read ({exc})")
        return 2
    fmt = args.format
    if fmt == "auto":
        name = path.name.lower()
        fmt = "svg" if name.endswith(".svg") else "drawio" if name.endswith((".drawio", ".xml")) else "mermaid" if name.endswith((".mmd", ".mermaid")) else None
    if fmt is None:
        msg = f"'{path.suffix or path.name}' is not a format this script reads (.svg, .drawio, .xml, .mmd)"
        print(msg)
        print(f"RESULT not verified: {msg}")
        return 2
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"RESULT not verified: the file could not be read as text ({exc})")
        return 2
    themes = ("light", "dark") if args.theme == "both" else (args.theme,)
    min_font = args.min_font or L["min_font_px"]
    print(f"diagram-check: {path} ({fmt})")
    if unverified:
        print(f"note: {len(unverified)} limit(s) in references/limits.json are unverified judgement values or estimates "
              f"(text {L['contrast_text_min']}:1, large {L['contrast_large_min']}:1, min font {r1(min_font)}px)")
    if fmt != "mermaid" and "<!ENTITY" in text:
        print("RESULT not verified: the file declares XML entities; it is not parsed, for safety")
        return 2
    try:
        if fmt == "mermaid":
            if not text.strip():
                raise InputError("the file is empty")
            findings, notes, styled, init_theme = check_mermaid(text, L, themes, min_font)
            print(f"read {styled} style/classDef line(s); theme: {init_theme or 'not set (checked as light and dark)'}")
            for rule, msg in findings:
                print(f"FAIL {rule:<11} {msg}")
            for line in notes:
                print(f"not measured: {line}")
            print("not measured: overlap, clipped, off-canvas, loose-edge and label sizes depend on the rendered layout; "
                  "export the diagram to SVG (for example with mermaid-cli) and run this script on the SVG")
            if findings:
                rules = sorted({r for r, _ in findings})
                print(f"RESULT fail: {len(findings)} finding(s): {', '.join(rules)}; layout not verified")
                return 1
            print("RESULT not verified: layout checks need a rendered SVG; style colours and font sizes passed")
            return 2
        if fmt == "svg":
            diagrams = [("", load_svg(text, args, L, themes))]
        else:
            diagrams = [(name, load_drawio_page(model, args, L, themes)) for name, model in drawio_pages(text)]
    except ET.ParseError as exc:
        print(f"RESULT not verified: the file is not well-formed XML ({exc})")
        return 2
    except InputError as exc:
        print(f"RESULT not verified: {exc}")
        return 2
    findings, not_measured, warnings, totals = [], [], [], [0, 0, 0]
    for page, D in diagrams:
        check(D, L, themes, min_font)
        prefix = f"[{page}] " if len(diagrams) > 1 else ""
        n_shapes = sum(1 for i in D.items if i["kind"] == "shape" and not i.get("paint_only"))
        n_text = sum(1 for i in D.items if i["kind"] == "text")
        n_edges = sum(1 for i in D.items if i["kind"] == "edge")
        totals = [totals[0] + n_shapes, totals[1] + n_text, totals[2] + n_edges]
        print(f"{prefix}canvas: {D.canvas_note}; {n_shapes} shape(s), {n_text} label(s), {n_edges} edge(s)"
              + (f"; font sizes scaled by {D.scale:.2f} to the display width" if D.kind == "svg" and abs(D.scale - 1) > 1e-6 else ""))
        findings += [(r, prefix + m) for r, m in D.findings]
        not_measured += [prefix + m for m in D.not_measured]
        warnings += [prefix + m for m in D.warnings]
    if not any(totals[:2]):
        print("RESULT not verified: no shapes or text found in the diagram")
        return 2
    summary = f"{totals[0]} shape(s), {totals[1]} label(s), {totals[2]} edge(s) checked in the {' and '.join(themes)} theme(s)"
    return report(findings, not_measured, warnings, summary)


if __name__ == "__main__":
    sys.exit(main())

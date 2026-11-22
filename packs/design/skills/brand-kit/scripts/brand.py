#!/usr/bin/env python3
"""Keep the user's brand in one file and check work against it.

  init   write a starting brand file (brand.json) with empty sections, for the user to fill in
         or confirm. It never overwrites an existing file.
  check  compare a page snapshot (design-review's format), stylesheets or text files with the
         brand file. Lists every colour and font that is not in the kit, with where it is,
         every banned phrase from the voice section, and contrast of each declared brand pair.

Colours match when every channel is within the brand file's tolerance (default 6 of 255).
Neutral greys can be allowed as a group with "allow_neutrals": true.

Exit codes: 0 = every value found is in the kit / file written
            1 = at least one off-kit colour, font or banned phrase, or a pair under its limit
            2 = not verified or blocked: no brand file, an unconfirmed brand file, nothing found
                to check, bad input
This script reads; `init` writes one new file. It never edits the user's work.
"""
import argparse
import colorsys
import json
import pathlib
import re
import sys

STYLE_EXT = {".css", ".scss", ".less", ".html", ".htm", ".jsx", ".tsx", ".vue", ".svelte", ".astro"}
TEXT_EXT = STYLE_EXT | {".md", ".txt", ".json", ".js", ".ts", ".mdx"}
SKIP_DIRS = {"node_modules", ".git", "dist", "build", ".next", "out", "coverage", "vendor", ".mstack", ".testrun"}
GENERIC_FONTS = {"serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui", "ui-sans-serif", "ui-serif",
                 "ui-monospace", "-apple-system", "blinkmacsystemfont", "inherit", "initial", "unset", "emoji", "math"}
HEX = re.compile(r"(?<![\w&])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![\w-])")
FUNC = re.compile(r"\brgba?\([^()]*\)|\bhsla?\([^()]*\)", re.I)
FONT_DECL = re.compile(r"font-family\s*:\s*([^;}{\n]+)", re.I)
TEMPLATE = {
    "name": "",
    "confirmed": False,
    "colors": [{"name": "primary", "value": "#000000", "use": "main actions", "never": "body text on dark backgrounds"}],
    "allow_neutrals": True,
    "tolerance": 6,
    "fonts": [{"family": "", "use": "headings"}],
    "pairs": [{"text": "primary", "background": "#ffffff", "min": 4.5}],
    "voice": {"we_say": [], "never_say": [], "examples": [{"off": "", "on": ""}]},
}


def stop(message):
    print(message)
    print(f"RESULT not verified: {message}")
    return 2


def parse_colour(text):
    t = text.strip().lower()
    m = re.fullmatch(r"#([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})", t)
    if m:
        h = m.group(1)
        h = "".join(c * 2 for c in h) if len(h) == 3 else h
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    m = re.fullmatch(r"(rgba?|hsla?)\(([^()]*)\)", t)
    if not m:
        return None
    parts = [p for p in re.split(r"[\s,/]+", m.group(2).strip()) if p]
    try:
        if m.group(1).startswith("rgb"):
            return tuple(float(p[:-1]) * 2.55 if p.endswith("%") else float(p) for p in parts[:3])
        h, s, l = float(parts[0].replace("deg", "")) / 360, float(parts[1].rstrip("%")) / 100, float(parts[2].rstrip("%")) / 100
        return tuple(c * 255 for c in colorsys.hls_to_rgb(h % 1, l, s))
    except (ValueError, IndexError):
        return None


def luminance(rgb):
    def linear(c):
        c = c / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * linear(rgb[0]) + 0.7152 * linear(rgb[1]) + 0.0722 * linear(rgb[2])


def ratio(a, b):
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def first_family(stack):
    for part in stack.split(","):
        name = part.strip().strip("\"'").lower()
        if name and name not in GENERIC_FONTS and not name.startswith("var("):
            return name
    return None


def load_brand(path):
    try:
        brand = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read brand file {path}: {exc}")
    palette = {}
    for c in brand.get("colors") or []:
        rgb = parse_colour(str(c.get("value", "")))
        if rgb is None:
            raise ValueError(f"brand file: colour {c.get('name')!r} has a value this script cannot read: {c.get('value')!r}")
        palette[c.get("name") or c["value"]] = rgb
    fonts = {str(f.get("family", "")).strip().lower() for f in brand.get("fonts") or [] if str(f.get("family", "")).strip()}
    if not palette or not fonts:
        raise ValueError("brand file needs at least one colour and one font family")
    return brand, palette, fonts


def in_kit(rgb, palette, tolerance, neutrals):
    for name, value in palette.items():
        if all(abs(rgb[i] - value[i]) <= tolerance for i in range(3)):
            return name
    if neutrals and max(rgb) - min(rgb) <= tolerance:
        return "neutral grey"
    return None


def gather(args):
    """Return lists of (value, where) for colours, fonts and text."""
    colours, fonts, texts = [], [], []
    if args.snapshot:
        data = json.loads(pathlib.Path(args.snapshot).read_text(encoding="utf-8"))
        views = data.get("views") if isinstance(data, dict) and "views" in data else [data]
        for view in views:
            if not isinstance(view, dict) or not isinstance(view.get("elements"), list):
                raise ValueError(f"{args.snapshot} is not a page snapshot")
            label = f"{(view.get('viewport') or {}).get('width', '?')}/{view.get('theme', 'light')}/{view.get('state', 'default')}"
            for el in view["elements"]:
                where = f"{label} {el.get('selector', '?')}"
                if (el.get("text") or "").strip():
                    colours.append((el.get("color", ""), where + " (text)"))
                    texts.append((el["text"], where))
                    family = first_family(el.get("fontFamily") or "")
                    if family:
                        fonts.append((family, where))
                if el.get("background") and el.get("backgroundKnown", True):
                    colours.append((el["background"], where + " (background)"))
    for folder in args.files or []:
        root = pathlib.Path(folder)
        if not root.exists():
            raise ValueError(f"{root} does not exist")
        paths = [root] if root.is_file() else [p for p in sorted(root.rglob("*")) if p.is_file() and p.suffix.lower() in TEXT_EXT
                                               and not any(part in SKIP_DIRS for part in p.relative_to(root).parts[:-1])]
        for path in paths:
            text = path.read_text(encoding="utf-8", errors="replace")
            for number, line in enumerate(text.splitlines(), 1):
                where = f"{path}:{number}"
                if path.suffix.lower() in STYLE_EXT:
                    for m in list(HEX.finditer(line)) + list(FUNC.finditer(line)):
                        if "var(" not in m.group(0) and not re.search(r"(href|id)\s*=\s*[\"']?$", line[:m.start()]):
                            colours.append((m.group(0), where))
                    for m in FONT_DECL.finditer(line):
                        family = first_family(m.group(1))
                        if family:
                            fonts.append((family, where))
                texts.append((line, where))
    return colours, fonts, texts


def cmd_init(args):
    target = pathlib.Path(args.out)
    if target.exists():
        return stop(f"{target} already exists and this script does not overwrite files")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(TEMPLATE, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {target}. Fill it from the user's own material, show it to the user, and set \"confirmed\": true only after they agree.")
    print("RESULT pass")
    return 0


def cmd_check(args):
    try:
        brand, palette, kit_fonts = load_brand(args.brand)
        if not brand.get("confirmed") and not args.draft:
            return stop("the brand file is not confirmed by the user; show it to them first, or pass --draft to check against it anyway")
        if not args.snapshot and not args.files:
            return stop("give --snapshot or --files to check")
        colours, fonts, texts = gather(args)
    except (OSError, ValueError) as exc:
        return stop(str(exc))
    tolerance = brand.get("tolerance", 6)
    neutrals = brand.get("allow_neutrals", True)
    off_colours, off_fonts, banned, weak_pairs = {}, {}, [], []
    for value, where in colours:
        rgb = parse_colour(value)
        if rgb is None or in_kit(rgb, palette, tolerance, neutrals):
            continue
        off_colours.setdefault("#%02x%02x%02x" % tuple(round(c) for c in rgb), []).append(where)
    for family, where in fonts:
        if family not in kit_fonts:
            off_fonts.setdefault(family, []).append(where)
    never = [p for p in (brand.get("voice") or {}).get("never_say") or [] if str(p).strip()]
    for line, where in texts:
        for phrase in never:
            if re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", line, re.I):
                banned.append((phrase, where, line.strip()[:80]))
    for pair in brand.get("pairs") or []:
        fg = palette.get(pair.get("text")) or parse_colour(str(pair.get("text", "")))
        bg = palette.get(pair.get("background")) or parse_colour(str(pair.get("background", "")))
        if fg and bg:
            got = ratio(fg, bg)
            if got < pair.get("min", 4.5):
                weak_pairs.append(f"{pair.get('text')} on {pair.get('background')}: {got:.2f}:1, under {pair.get('min', 4.5)}:1")
    for value, places in sorted(off_colours.items()):
        print(f"OFF colour {value} in {len(places)} place(s): " + "; ".join(places[:4]) + (" ..." if len(places) > 4 else ""))
    for family, places in sorted(off_fonts.items()):
        print(f"OFF font   {family} in {len(places)} place(s): " + "; ".join(places[:4]) + (" ..." if len(places) > 4 else ""))
    for phrase, where, line in banned:
        print(f"OFF voice  '{phrase}' at {where}: {line}")
    for line in weak_pairs:
        print(f"OFF pair   {line}")
    print(f"brand {brand.get('name') or args.brand}{' (draft, not confirmed)' if not brand.get('confirmed') else ''}: "
          f"{len(palette)} colours, {len(kit_fonts)} fonts, {len(never)} banned phrases")
    print(f"checked {len(colours)} colour uses, {len(fonts)} font uses, {len(texts)} text lines: "
          f"{len(off_colours)} off-kit colours, {len(off_fonts)} off-kit fonts, {len(banned)} banned phrases, {len(weak_pairs)} weak pairs")
    print("not seen by this check: logos and images, tone beyond the banned phrases, and colours inside SVG or image files")
    if not colours and not fonts and not texts:
        return stop("nothing to check was found in the given input")
    total = len(off_colours) + len(off_fonts) + len(banned) + len(weak_pairs)
    if total:
        print(f"RESULT fail: {total} off-kit item(s)")
        return 1
    print("RESULT pass")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("init", help="write a starting brand file")
    p.add_argument("--out", default="brand.json", help="new brand file (default brand.json)")
    p = sub.add_parser("check", help="compare work with the brand file")
    p.add_argument("--brand", default="brand.json", help="brand file (default brand.json)")
    p.add_argument("--snapshot", help="page snapshot JSON from design-review's collector")
    p.add_argument("--files", nargs="+", help="stylesheets, markup or text files or folders")
    p.add_argument("--draft", action="store_true", help="check against a brand file the user has not confirmed yet")
    args = parser.parse_args()
    return {"init": cmd_init, "check": cmd_check}[args.action](args)


if __name__ == "__main__":
    sys.exit(main())

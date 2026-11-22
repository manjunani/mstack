#!/usr/bin/env python3
"""Check a project's colour and spacing tokens, and find values that bypass them. No browser.

  contrast  read CSS custom properties (and a simple Tailwind config), measure every
            text-on-background pair in the light and the dark theme with the WCAG 2.x
            formula, and propose a passing value of the same hue for each failure
  drift     list hard-coded colours and off-scale sizes in source files

Pairs come from a pairs file (--pairs) or, when there is none, from token names
(--x-foreground on --x, --on-x on --x, --text on --background and similar). Inferred
pairs are marked so the user can confirm them.

Exit codes: 0 = every measured pair passes / no drift
            1 = a pair is under its limit, or a value bypasses the tokens
            2 = not verified or blocked: no tokens, no pairs, a colour that could not be
                measured, or bad input
This script reads files and prints. With --report it writes one new JSON file.
"""
import argparse
import colorsys
import fnmatch
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
LIMITS = HERE.parent / "references" / "limits.json"
SOURCE_EXT = {".css", ".scss", ".sass", ".less", ".html", ".htm", ".jsx", ".tsx", ".js", ".ts", ".vue", ".svelte", ".astro"}
STYLE_EXT = {".css", ".scss", ".sass", ".less"}
SKIP_DIRS = {"node_modules", ".git", "dist", "build", ".next", "out", "coverage", "vendor", ".mstack", ".testrun", "__pycache__"}
NAMED = {"black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0), "green": (0, 128, 0), "blue": (0, 0, 255),
         "yellow": (255, 255, 0), "gray": (128, 128, 128), "grey": (128, 128, 128), "silver": (192, 192, 192),
         "navy": (0, 0, 128), "teal": (0, 128, 128), "orange": (255, 165, 0), "purple": (128, 0, 128),
         "maroon": (128, 0, 0), "olive": (128, 128, 0), "lime": (0, 255, 0), "aqua": (0, 255, 255),
         "cyan": (0, 255, 255), "fuchsia": (255, 0, 255), "magenta": (255, 0, 255)}
DARK = re.compile(r"prefers-color-scheme\s*:\s*dark|\.dark\b|\.theme-dark\b|\[data-(theme|mode|color-scheme)\s*=\s*[\"']?dark", re.I)
ROOTISH = re.compile(r"^(:root|html|body|:host|\*)\b|^@theme\b|\.light\b|\[data-(theme|mode|color-scheme)\s*=\s*[\"']?light", re.I)
UNSUPPORTED = re.compile(r"\b(oklch|oklab|lch|lab|color-mix|color)\(", re.I)
HEX = re.compile(r"(?<![\w&])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![\w-])")
FUNC = re.compile(r"\b(?:rgba?|hsla?)\([^()]*\)", re.I)
SIZE_PROPS = re.compile(r"^(margin|padding|gap|row-gap|column-gap|font-size|border-radius)(-[a-z-]+)?$")
ARBITRARY_SIZE = re.compile(r"(?<![\w-])((?:p|m|gap|space|text|rounded)[a-z]?(?:-[xytblrse])?)-\[(\d+(?:\.\d+)?)(px|rem)\]")


def fail_input(message):
    print(message)
    print(f"RESULT not verified: {message}")
    return 2


# ---------- colour ----------

def _number(part, scale=1.0):
    part = part.strip()
    return float(part[:-1]) / 100 * scale if part.endswith("%") else float(part)


def parse_colour(text):
    """Return (r, g, b, alpha) with channels 0-255 and alpha 0-1, or None when the text is not a colour this script reads."""
    t = text.strip().lower()
    if t in NAMED:
        return (*NAMED[t], 1.0)
    if t == "transparent":
        return (0, 0, 0, 0.0)
    m = re.fullmatch(r"#([0-9a-f]{3,8})", t)
    if m:
        h = m.group(1)
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h)
        if len(h) not in (6, 8):
            return None
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        return (r, g, b, int(h[6:8], 16) / 255 if len(h) == 8 else 1.0)
    m = re.fullmatch(r"(rgba?|hsla?)\(([^()]*)\)", t)
    kind, inner = (m.group(1), m.group(2)) if m else ("hsl", t)
    if not m and not re.fullmatch(r"-?[\d.]+(deg)?\s+[\d.]+%\s+[\d.]+%(\s*/\s*[\d.]+%?)?", t):
        return None  # a bare "222 47% 11%" triplet is read as HSL, the way many token files store it
    parts = [p for p in re.split(r"[\s,/]+", inner.strip()) if p]
    if len(parts) not in (3, 4):
        return None
    try:
        alpha = min(1.0, max(0.0, _number(parts[3]))) if len(parts) == 4 else 1.0
        if kind.startswith("rgb"):
            r, g, b = (min(255.0, max(0.0, _number(p, 255.0))) for p in parts[:3])
        else:
            hue = float(parts[0].replace("deg", "")) % 360 / 360
            sat, light = _number(parts[1] if parts[1].endswith("%") else parts[1] + "%"), _number(parts[2] if parts[2].endswith("%") else parts[2] + "%")
            r, g, b = (c * 255 for c in colorsys.hls_to_rgb(hue, min(1.0, light), min(1.0, sat)))
    except ValueError:
        return None
    return (r, g, b, alpha)


def luminance(rgb):
    """WCAG 2.x relative luminance of an sRGB colour with channels 0-255."""
    def linear(c):
        c = c / 255
        # WCAG prints 0.03928; the sRGB standard says 0.04045. No 8-bit value lies between them.
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (linear(c) for c in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(a, b):
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def over(top, under):
    """Composite a colour with alpha over an opaque colour."""
    a = top[3]
    return tuple(round(top[i] * a + under[i] * (1 - a)) for i in range(3))


def to_hex(rgb):
    return "#%02x%02x%02x" % tuple(int(round(c)) for c in rgb[:3])


def propose(text, backgrounds, limit):
    """Nearest lightness of the same hue and saturation that reaches the limit on every background."""
    hue, light, sat = colorsys.rgb_to_hls(*(c / 255 for c in text[:3]))
    best = None
    for step in range(0, 1001):
        cand = tuple(int(round(c * 255)) for c in colorsys.hls_to_rgb(hue, step / 1000, sat))
        if all(ratio(cand, bg) >= limit for bg in backgrounds):
            distance = abs(step / 1000 - light)
            if best is None or distance < best[0]:
                best = (distance, cand)
    return best[1] if best else None


# ---------- reading tokens ----------

def strip_comments(text):
    return re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)


def css_declarations(text):
    """Yield (name, value, line, enclosing preludes) for every custom property declaration."""
    text = strip_comments(text)
    stack, buf, line, start, depth, quote = [], "", 1, 1, 0, ""
    for ch in text:
        if ch == "\n":
            line += 1
        if quote:
            buf += ch
            quote = "" if ch == quote else quote
            continue
        if ch in "\"'":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if depth == 0 and ch in "{};":
            piece = buf.strip()
            if ch == "{":
                stack.append(piece)
            else:
                name, sep, value = piece.partition(":")
                if sep and name.strip().startswith("--"):
                    yield name.strip(), value.strip(), start, list(stack)
                if ch == "}" and stack:
                    stack.pop()
            buf, start = "", line
        else:
            if not buf.strip():
                start = line
            buf += ch


def read_css_tokens(paths):
    themes = {"light": {}, "dark": {}}
    where, scoped = {}, 0
    for path in paths:
        for name, value, line, stack in css_declarations(path.read_text(encoding="utf-8", errors="replace")):
            chain = " ".join(stack)
            if DARK.search(chain):
                theme = "dark"
            elif not stack or any(ROOTISH.search(s) for s in stack):
                theme = "light"
            else:
                scoped += 1
                continue
            themes[theme][name] = value
            where[(theme, name)] = f"{path}:{line}"
    return themes, where, scoped


def read_tailwind(path):
    """Read literal colours from the colors block of a Tailwind config. Returns (tokens, notes)."""
    text = re.sub(r"//[^\n]*", "", strip_comments(path.read_text(encoding="utf-8", errors="replace")))
    start = re.search(r"\bcolors\s*:\s*\{", text)
    if not start:
        return {}, [f"{path.name}: no literal colors block found"]
    depth, i = 1, start.end()
    while i < len(text) and depth:
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        i += 1
    block = text[start.end():i - 1]
    tokens, names, skipped = {}, [], 0
    token = re.compile(r"""(['"]?)([\w-]+)\1\s*:\s*(?:(['"])(.*?)\3|(\{))|(\})|(\.\.\.|require\(|=>|\w+\()""", re.S)
    for m in token.finditer(block):
        if m.group(6):
            names = names[:-1]
        elif m.group(7):
            skipped += 1
        elif m.group(5):
            names.append(m.group(2))
        elif m.group(2):
            key = "-".join(names + ([] if m.group(2) == "DEFAULT" else [m.group(2)]))
            tokens["tw:" + key] = m.group(4)
    notes = [f"{path.name}: {len(tokens)} literal colours read"]
    if skipped:
        notes.append(f"{path.name}: not a simple config; {skipped} computed entries (spread, require or function) were skipped")
    return tokens, notes


def resolve(value, theme_map, fallback_map, depth=0):
    """Replace var(--x) and var(--x, fallback) with their values."""
    if depth > 12:
        return value
    def swap(m):
        name, _, default = m.group(1).partition(",")
        found = theme_map.get(name.strip(), fallback_map.get(name.strip()))
        if found is None:
            found = default.strip() if default.strip() else m.group(0)
        return found
    new = re.sub(r"var\(\s*([^()]*)\)", swap, value)
    return resolve(new, theme_map, fallback_map, depth + 1) if new != value and "var(" in new else new


def size_px(value):
    m = re.fullmatch(r"(-?\d*\.?\d+)(px|rem)", value.strip())
    return round(float(m.group(1)) * (16 if m.group(2) == "rem" else 1), 3) if m else None


def load_limits():
    data = json.loads(LIMITS.read_text(encoding="utf-8"))
    unverified = sorted(k for k, v in data.items() if isinstance(v, dict) and not v.get("verified"))
    if unverified:
        print(f"note: these limits were written from memory and not checked against the source: {', '.join(unverified)} (see references/limits.json)")
    return {k: v["value"] for k, v in data.items() if isinstance(v, dict)}


def background_candidates(name):
    base = name[2:]
    out = []
    if base in ("foreground", "text", "fg", "text-color", "color-text", "color-fg", "color-foreground"):
        out += ["--background", "--bg", "--background-color", "--bg-color", "--color-background", "--color-bg"]
    if base.endswith("-foreground"):
        out.append("--" + base[:-11])
    if base.startswith("on-"):
        out.append("--" + base[3:])
    if "text-on-" in base:
        out.append("--" + base.replace("text-on-", ""))
    for tail in ("-fg", "-text"):
        if base.endswith(tail):
            stem = base[:-len(tail)]
            out += [f"--{stem}-bg", f"--{stem}-background", f"--{stem}"]
    return out


def infer_pairs(names):
    pairs = []
    for name in sorted(names):
        plain = name[3:] if name.startswith("tw:") else None
        candidates = background_candidates("--" + plain) if plain else background_candidates(name)
        for cand in candidates:
            target = "tw:" + cand[2:] if plain else cand
            if target in names and target != name:
                pairs.append({"text": name, "background": target, "inferred": True})
                break
    return pairs


def load_reasoned(path, need):
    """Read a waiver or accept file: a list of objects, each with a reason of at least 8 characters."""
    try:
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(fail_input(f"cannot read {path}: {exc}"))
    if not isinstance(data, list):
        raise SystemExit(fail_input(f"{path} must hold a JSON list"))
    for entry in data:
        if not isinstance(entry, dict) or len(str(entry.get("reason", "")).strip()) < 8:
            raise SystemExit(fail_input(f"{path}: every entry needs a reason of at least 8 characters: {json.dumps(entry)}"))
        if not any(entry.get(k) for k in need):
            raise SystemExit(fail_input(f"{path}: every entry needs one of {', '.join(need)}: {json.dumps(entry)}"))
    return data


def write_report(path, data):
    target = pathlib.Path(path)
    if target.exists():
        print(f"report not written: {target} already exists and this script does not overwrite files")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"report written to {target}")


def gather_tokens(args):
    css = [pathlib.Path(p) for p in args.css]
    missing = [str(p) for p in css if not p.is_file()]
    if args.tailwind and not pathlib.Path(args.tailwind).is_file():
        missing.append(args.tailwind)
    if missing:
        raise SystemExit(fail_input(f"file not found: {', '.join(missing)}"))
    themes, where, scoped = read_css_tokens(css)
    notes = []
    if scoped:
        notes.append(f"custom properties scoped to a component selector, not read as tokens: {scoped}")
    if args.tailwind:
        tw, tw_notes = read_tailwind(pathlib.Path(args.tailwind))
        themes["light"].update(tw)
        notes += tw_notes
    return themes, where, notes


# ---------- contrast ----------

def cmd_contrast(args):
    limits = load_limits()
    themes, where, notes = gather_tokens(args)
    for note in notes:
        print("note: " + note)
    light, dark = themes["light"], themes["dark"]
    if not light and not dark:
        return fail_input("no custom properties found on :root, html, body, @theme or a dark selector")
    names = set(light) | set(dark)
    if args.pairs:
        pairs = load_reasoned_pairs(args.pairs)
    else:
        pairs = infer_pairs(names)
        if pairs:
            print(f"note: no pairs file given; {len(pairs)} pairs were inferred from token names. Show them to the user, or pass --pairs.")
    if not pairs:
        return fail_input("no text-on-background pairs: the token names follow no pattern this script knows. Write a pairs file (see references/pairs-format.md) and pass --pairs")
    waivers = load_reasoned(args.waivers, ("text", "background")) if args.waivers else []
    theme_names = ["light"] + (["dark"] if dark else [])
    if not dark:
        print("note: no dark theme tokens found; only the light theme was measured")
    results, failures, unmeasured, waived = [], [], [], []
    for theme in theme_names:
        table = dict(light, **dark) if theme == "dark" else light
        for pair in pairs:
            label = f"{pair['text']} on {pair['background']} [{theme}]"
            raw = [table.get(pair["text"]), table.get(pair["background"])]
            if raw[0] is None or raw[1] is None:
                gone = pair["text"] if raw[0] is None else pair["background"]
                unmeasured.append(f"{label}: token {gone} is not defined")
                continue
            values = [resolve(v, table, light) for v in raw]
            if theme == "dark" and pair["text"].startswith("tw:") and values == [resolve(light.get(pair[k], ""), light, light) for k in ("text", "background")]:
                continue  # a Tailwind colour that does not change with the theme was already measured
            colours = [parse_colour(v) for v in values]
            if None in colours:
                bad = values[colours.index(None)]
                why = "colour space not supported by this script" if UNSUPPORTED.search(bad) else "not a colour this script can read"
                unmeasured.append(f"{label}: {bad!r} is {why}")
                continue
            text, background = colours
            if background[3] < 1:
                unmeasured.append(f"{label}: the background is translucent, so what is under it decides the result")
                continue
            shown = over(text, background)
            limit = limits["contrast_large_min"] if pair.get("large") or pair.get("kind") in ("large", "ui") else limits["contrast_text_min"]
            got = ratio(shown, background)
            row = {"theme": theme, "text": pair["text"], "background": pair["background"], "ratio": round(got, 2), "limit": limit,
                   "text_value": to_hex(shown), "background_value": to_hex(background), "inferred": bool(pair.get("inferred")),
                   "where": where.get((theme, pair["text"]), where.get(("light", pair["text"]), "")), "pass": got >= limit}
            results.append(row)
            if got < limit:
                waiver = next((w for w in waivers if w.get("text", pair["text"]) == pair["text"]
                               and w.get("background", pair["background"]) == pair["background"]
                               and w.get("theme", theme) == theme), None)
                if waiver:
                    row["waived"] = waiver["reason"]
                    waived.append(row)
                else:
                    failures.append(row)
    for row in results:
        mark = "ok  " if row["pass"] else ("waiv" if row.get("waived") else "FAIL")
        tag = " (inferred pair)" if row["inferred"] else ""
        print(f"{mark} {row['ratio']:5.2f}:1 (limit {row['limit']}) {row['text']} {row['text_value']} on {row['background']} {row['background_value']} [{row['theme']}]{tag}")
    # One proposal per failing text token and theme: a value that passes on every background it is paired with.
    seen = set()
    for row in failures:
        key = (row["theme"], row["text"])
        if key in seen:
            continue
        seen.add(key)
        mates = [r for r in results if (r["theme"], r["text"]) == key]
        backgrounds = [parse_colour(r["background_value"]) for r in mates]
        limit = max(r["limit"] for r in mates)
        fix = propose(parse_colour(row["text_value"]), backgrounds, limit)
        row_where = f" ({row['where']})" if row["where"] else ""
        if fix:
            worst = min(ratio(fix, bg) for bg in backgrounds)
            row["proposal"] = to_hex(fix)
            print(f"  fix {row['text']} [{row['theme']}]{row_where}: {row['text_value']} -> {to_hex(fix)} keeps the hue and gives at least {worst:.2f}:1 on {len(mates)} background(s)")
        else:
            print(f"  fix {row['text']} [{row['theme']}]{row_where}: no lightness of this hue reaches {limit}:1 on all of its {len(mates)} background(s); change a background or split the token")
    for line in unmeasured:
        print("not measured: " + line)
    for row in waived:
        print(f"waived: {row['text']} on {row['background']} [{row['theme']}]: {row['waived']}")
    print(f"checked {len(results)} pair measurements in {len(theme_names)} theme(s): {len(failures)} under the limit, {len(waived)} waived, {len(unmeasured)} not measured")
    print("not seen by this check: text on images or gradients, opacity set in components, and colours that never became tokens (run drift)")
    if args.report:
        write_report(args.report, {"pairs": results, "not_measured": unmeasured})
    if failures:
        print(f"RESULT fail: {len(failures)} pair(s) under the contrast limit")
        return 1
    if unmeasured:
        print(f"RESULT not verified: {len(unmeasured)} pair(s) could not be measured")
        return 2
    if not results:
        return fail_input("no pair could be measured")
    print("RESULT pass")
    return 0


def load_reasoned_pairs(path):
    try:
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(fail_input(f"cannot read {path}: {exc}"))
    pairs = data.get("pairs") if isinstance(data, dict) else data
    if not isinstance(pairs, list) or not pairs:
        raise SystemExit(fail_input(f"{path} holds no pairs"))
    for pair in pairs:
        if not isinstance(pair, dict) or not pair.get("text") or not pair.get("background"):
            raise SystemExit(fail_input(f"{path}: each pair needs text and background: {json.dumps(pair)}"))
    return pairs


# ---------- drift ----------

def source_files(root, skip):
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SOURCE_EXT or ".min." in path.name:
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts[:-1]):
            continue
        if path.resolve() in skip or re.match(r"tailwind\.config\.", path.name):
            continue
        files.append(path)
    return files


def nearest_token(colour, palette):
    best = None
    for name, value in palette.items():
        distance = sum((colour[i] - value[i]) ** 2 for i in range(3)) ** 0.5
        if best is None or distance < best[0]:
            best = (distance, name)
    return best


def cmd_drift(args):
    root = pathlib.Path(args.source)
    if not root.is_dir():
        return fail_input(f"not a folder: {root}")
    themes, _, notes = gather_tokens(args)
    for note in notes:
        print("note: " + note)
    light = themes["light"]
    palette, scale = {}, {}
    for theme in ("light", "dark"):
        table = dict(light, **themes["dark"]) if theme == "dark" else light
        for name in themes[theme]:
            value = resolve(themes[theme][name], table, light)
            colour = parse_colour(value)
            if colour:
                palette.setdefault(f"{name} [{theme}]" if theme == "dark" else name, colour)
            elif size_px(value) is not None:
                scale.setdefault(size_px(value), name)
    if not palette:
        return fail_input("no colour tokens found in the given files, so there is nothing to compare the source with")
    accepted = load_reasoned(args.accept, ("value", "path")) if args.accept else []
    files = source_files(root, {pathlib.Path(p).resolve() for p in args.css})
    if not files:
        return fail_input(f"no source files found under {root}")
    findings, warnings, uses, used_accepts = [], [], {}, set()

    def is_accepted(value, rel):
        for i, entry in enumerate(accepted):
            if entry.get("value") and entry["value"].lower() != value.lower():
                continue
            if entry.get("path") and not fnmatch.fnmatch(rel, entry["path"]):
                continue
            used_accepts.add(i)
            return True
        return False

    for path in files:
        rel = str(path.relative_to(root))
        style = path.suffix.lower() in STYLE_EXT
        text = path.read_text(encoding="utf-8", errors="replace")
        text = strip_comments(text) if style or path.suffix.lower() in (".vue", ".svelte", ".astro", ".html", ".htm") else text
        for number, line in enumerate(text.splitlines(), 1):
            line = re.sub(r"--[\w-]+\s*:[^;{}]*;?", "", line)  # a token definition is not a use
            for m in list(HEX.finditer(line)) + list(FUNC.finditer(line)):
                literal = m.group(0)
                before = line[:m.start()]
                if "var(" in literal or re.search(r"(href|to|id|for|url)\s*[=(]\s*[\"']?$", before):
                    continue
                if not style and literal.startswith("#") and not re.search(r"[\"'`\[:]\s*$", before):
                    continue  # in script and markup, count a hex only where a colour value can stand
                colour = parse_colour(literal)
                if colour is None or is_accepted(literal, rel):
                    continue
                distance, name = nearest_token(colour, palette)
                hint = f"same value as {name}; use the token" if distance < 0.5 else f"not a token; nearest is {name}"
                findings.append({"kind": "colour", "file": rel, "line": number, "value": literal, "hint": hint})
            sizes = []
            if style:
                for decl in re.finditer(r"(?<![\w-])([a-z-]+)\s*:\s*([^;{}]+)", line):
                    if SIZE_PROPS.match(decl.group(1)) and "var(" not in decl.group(2):
                        sizes += [(m.group(0), size_px(m.group(0))) for m in re.finditer(r"(?<![\w.-])\d*\.?\d+(?:px|rem)\b", decl.group(2))]
            else:
                sizes = [(m.group(0), size_px(m.group(2) + m.group(3))) for m in ARBITRARY_SIZE.finditer(line)]
            for literal, px in sizes:
                if px is None or px in (0, 1) or is_accepted(literal, rel):
                    continue
                uses.setdefault(px, []).append((rel, number, literal))
    if scale:
        steps = sorted(scale)
        for px, places in sorted(uses.items()):
            if px in scale:
                continue
            near = min(steps, key=lambda s: abs(s - px))
            for rel, number, literal in places:
                findings.append({"kind": "size", "file": rel, "line": number, "value": literal,
                                 "hint": f"{px:g}px is off the scale; nearest step is {scale[near]} ({near:g}px)"})
    else:
        for px, places in sorted(uses.items()):
            if len(places) == 1:
                rel, number, literal = places[0]
                warnings.append(f"{rel}:{number}: {literal} is used once in the whole source (no size tokens exist to compare with)")
    findings.sort(key=lambda f: (f["file"], f["line"]))
    for f in findings[:args.max_lines]:
        print(f"DRIFT {f['kind']:6} {f['file']}:{f['line']}: {f['value']}  {f['hint']}")
    if len(findings) > args.max_lines:
        print(f"... {len(findings) - args.max_lines} more; pass --report <new file> for the full list")
    for line in warnings[:args.max_lines]:
        print("warn " + line)
    for i, entry in enumerate(accepted):
        if i not in used_accepts:
            print(f"note: accept entry matched nothing and can be removed: {json.dumps(entry)}")
    colours = sum(1 for f in findings if f["kind"] == "colour")
    print(f"scanned {len(files)} files against {len(palette)} colour tokens and {len(scale)} size steps: "
          f"{colours} hard-coded colours, {len(findings) - colours} off-scale sizes, {len(used_accepts)} accept entries used, {len(warnings)} warnings")
    print("not seen by this check: colours built at run time, values inside images and SVG files, and third-party styles")
    if args.report:
        write_report(args.report, {"findings": findings, "warnings": warnings})
    if findings:
        print(f"RESULT fail: {len(findings)} value(s) bypass the tokens")
        return 1
    print("RESULT pass")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("contrast", help="measure text-on-background token pairs in light and dark")
    p.add_argument("css", nargs="+", help="CSS files that define the tokens as custom properties")
    p.add_argument("--tailwind", help="a tailwind.config file whose literal colours are read as tokens named tw:<key>")
    p.add_argument("--pairs", help="JSON file of pairs: [{\"text\": \"--fg\", \"background\": \"--bg\", \"large\": false}]")
    p.add_argument("--waivers", help="JSON list of waived pairs, each with text or background, and a reason")
    p.add_argument("--report", help="write the measurements to this new JSON file")
    p = sub.add_parser("drift", help="list hard-coded colours and off-scale sizes in source files")
    p.add_argument("source", help="folder of source files to scan")
    p.add_argument("--css", nargs="+", required=True, help="CSS files that define the tokens")
    p.add_argument("--tailwind", help="a tailwind.config file whose literal colours count as tokens")
    p.add_argument("--accept", help="JSON list of accepted values: [{\"value\": \"#fff\", \"path\": \"legacy/*\", \"reason\": \"...\"}]")
    p.add_argument("--report", help="write every finding to this new JSON file")
    p.add_argument("--max-lines", type=int, default=60, help="findings to print before cutting the list (default 60)")
    args = parser.parse_args()
    return {"contrast": cmd_contrast, "drift": cmd_drift}[args.action](args)


if __name__ == "__main__":
    sys.exit(main())

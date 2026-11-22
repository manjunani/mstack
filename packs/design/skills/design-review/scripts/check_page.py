#!/usr/bin/env python3
"""Gate a rendered page from a snapshot of what the browser really drew.

  merge  join the views that scripts/collect.js returned (one per viewport, theme and
         state) into one snapshot file
  check  read a snapshot and report what blocks, what only warns and what could not be judged

Blocks: content cut off or wider than the viewport, text contrast under the limit on its
measured background, a control or image with no accessible name, a target under the size
limit, and placeholder or unrendered text. Warnings: traits of a generic default look, and
other matters of taste; they never change the result. A finding can be waived only by an
entry in a waivers file that names the rule and the selector and gives a reason.

Exit codes: 0 = no blocking finding in any required view
            1 = at least one blocking finding
            2 = not verified or blocked: a required viewport or theme is missing, an element
                could not be judged, the snapshot is empty or unreadable, a bad waiver
The snapshot format is in references/snapshot-format.md. This script never edits the
snapshot. merge and --report write new files and refuse to replace existing ones.
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
LOOKS = HERE.parent / "references" / "default-looks.json"
NAME_ROLES = {"button", "link", "textbox", "searchbox", "combobox", "listbox", "checkbox", "radio", "switch", "slider",
              "spinbutton", "tab", "menuitem", "menuitemcheckbox", "menuitemradio", "img"}
PLACEHOLDER = [
    (re.compile(r"lorem ipsum|dolor sit amet|consectetur adipisc", re.I), "filler Latin"),
    (re.compile(r"\b(TODO|FIXME|TBD|XXX)\b"), "a work marker"),
    (re.compile(r"\b(placeholder|dummy|sample) (text|copy|title|heading|content|data)\b", re.I), "placeholder wording"),
    (re.compile(r"\b(your|insert|add) [\w ]{0,24}\bhere\b|\bgoes here\b", re.I), "placeholder wording"),
    (re.compile(r"\{\{[^{}]*\}\}|\[object Object\]"), "a value that was never filled in"),
    (re.compile(r"^(undefined|null|NaN|untitled|heading|subtitle|button text|link text)$", re.I), "a default or empty value shown as text"),
]
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")


class BadInput(Exception):
    pass


# ---------- colour (WCAG 2.x) ----------

def parse_colour(text):
    """Return (r, g, b, alpha) from a computed colour such as rgb(1, 2, 3), rgba(1, 2, 3, 0.5) or #aabbcc, else None."""
    t = (text or "").strip().lower()
    m = re.fullmatch(r"#([0-9a-f]{6}|[0-9a-f]{8}|[0-9a-f]{3})", t)
    if m:
        h = m.group(1)
        h = "".join(c * 2 for c in h) if len(h) == 3 else h
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16) / 255 if len(h) == 8 else 1.0)
    m = re.fullmatch(r"rgba?\(([^()]*)\)", t)
    if not m:
        return None
    parts = [p for p in re.split(r"[\s,/]+", m.group(1).strip()) if p]
    try:
        r, g, b = (float(p) for p in parts[:3])
        a = 1.0 if len(parts) < 4 else (float(parts[3][:-1]) / 100 if parts[3].endswith("%") else float(parts[3]))
    except (ValueError, IndexError):
        return None
    return (r, g, b, min(1.0, max(0.0, a)))


def luminance(rgb):
    def linear(c):
        c = c / 255
        # WCAG prints 0.03928; the sRGB standard says 0.04045. No 8-bit value lies between them.
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * linear(rgb[0]) + 0.7152 * linear(rgb[1]) + 0.0722 * linear(rgb[2])


def ratio(a, b):
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def over(top, under):
    return tuple(top[i] * top[3] + under[i] * (1 - top[3]) for i in range(3))


# ---------- snapshot reader (format 1; the same reader is repeated in a11y-audit and ui-copy) ----------

def load_json(path):
    try:
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        if isinstance(data, str):  # some browser tools hand back the JSON as a quoted string
            data = json.loads(data)
    except (OSError, ValueError) as exc:
        raise BadInput(f"cannot read {path}: {exc}")
    return data


def views_of(data, path):
    if isinstance(data, dict) and isinstance(data.get("views"), list):
        views = data["views"]
    elif isinstance(data, dict) and "elements" in data:
        views = [data]
    else:
        raise BadInput(f"{path} is not a snapshot: it has neither 'views' nor 'elements'")
    for view in views:
        width = (view.get("viewport") or {}).get("width") if isinstance(view, dict) else None
        if not isinstance(width, (int, float)) or not isinstance(view.get("elements"), list):
            raise BadInput(f"{path}: every view needs viewport.width and a list of elements")
    return views


def label_of(view):
    return f"{view['viewport']['width']:g}/{view.get('theme', 'light')}/{view.get('state', 'default')}"


def load_data(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    values = {k: v["value"] for k, v in data.items() if isinstance(v, dict) and "value" in v}
    unverified = sorted(k for k, v in data.items() if isinstance(v, dict) and "value" in v and not v.get("verified"))
    return values, unverified, data


# ---------- checks ----------

def check_view(view, limits, looks):
    found = []
    name = label_of(view)
    width = view["viewport"]["width"]
    slack = limits["overflow_slack_px"]

    def add(level, rule, el, detail):
        found.append({"level": level, "rule": rule, "view": name, "selector": el.get("selector", "?") if el else "html",
                      "text": ((el.get("text") or el.get("name") or "") if el else "")[:60], "detail": detail})

    page = view.get("document") or {}
    if page.get("scrollWidth", 0) > width + slack:
        add("block", "page-overflow", None, f"the page is {page['scrollWidth']:g} px wide in a {width:g} px viewport, so it scrolls sideways")
    if view.get("skipped"):
        add("unverified", "coverage", None, f"the collector left out {view['skipped']} elements beyond its limit")
    targets = [e for e in view["elements"] if e.get("interactive") and e.get("box") and not e.get("visuallyHidden")]
    for el in view["elements"]:
        box = el.get("box") or {}
        text = (el.get("text") or "").strip()
        hidden = bool(el.get("visuallyHidden"))
        active = bool(el.get("interactive") or el.get("focusable"))
        role = el.get("role") or ""
        label = (el.get("name") or "").strip()

        if not hidden:
            if el.get("clipped"):
                add("block", "clipped", el, "the text is cut off by its own box")
            elif el.get("clippedBy"):
                add("block", "clipped", el, f"cut off by {el['clippedBy']}")
            elif el.get("truncated"):
                add("warn", "truncated", el, f"shortened with {el['truncated']}; make sure the full text can be reached")
            if box and (text or active) and not el.get("inScroller"):
                left, right = box.get("x", 0), box.get("x", 0) + box.get("width", 0)
                if left < width - slack and right > width + slack:
                    add("block", "clipped", el, f"runs {right - width:g} px past the right edge of the {width:g} px viewport")
                elif left < -slack and right > slack:
                    add("block", "clipped", el, f"starts {-left:g} px left of the viewport")

        if text and not hidden and not el.get("disabled"):
            fg, bg = parse_colour(el.get("color")), parse_colour(el.get("background"))
            if el.get("backgroundKnown") is False or fg is None or bg is None or bg[3] < 1:
                add("unverified", "contrast", el, "the text sits on an image, a gradient or an unknown background; look at it and waive with a reason, or give it a solid backing")
            else:
                size, weight = el.get("fontSize") or 16, el.get("fontWeight") or 400
                large = size >= limits["large_text_px"] or (size >= limits["large_bold_text_px"] and weight >= 700)
                limit = limits["contrast_large_min"] if large else limits["contrast_text_min"]
                got = ratio(over(fg, bg), bg)
                if got < limit:
                    add("block", "contrast", el, f"{got:.2f}:1 is under {limit}:1 ({el.get('color')} on {el.get('background')}, {size:g} px{' bold' if weight >= 700 else ''})")
            if size_of(el) and size_of(el) < looks["min_readable_px"]:
                add("warn", "tiny-text", el, f"{size_of(el):g} px text is hard to read")

        if (active or role in NAME_ROLES) and not label and not el.get("decorative"):
            what = "image has no text alternative" if role == "img" or el.get("tag") == "img" else f"{role or el.get('tag', 'control')} has no accessible name"
            add("block", "no-name", el, what)
        elif el.get("nameFrom") == "placeholder":
            add("warn", "weak-name", el, "named only by its placeholder, which vanishes when the user types")

        if el.get("interactive") and box and not hidden and not el.get("inline") and not el.get("disabled"):
            w, h = box.get("width", 0), box.get("height", 0)
            least = limits["target_min_px"]
            if w < least or h < least:
                mine = space_of(box, least)
                crowded = any(o is not el and overlap(mine, space_of(o["box"], least)) for o in targets)
                if crowded:
                    add("block", "small-target", el, f"{w:g} x {h:g} px, under {least:g} x {least:g}, and closer than {least:g} px (centre to centre) to another target")
                else:
                    add("warn", "small-target", el, f"{w:g} x {h:g} px, under {least:g} x {least:g}; allowed only because no other target is that close")
            elif width <= looks["phone_max_width"] and (w < looks["touch_comfort_px"] or h < looks["touch_comfort_px"]):
                add("warn", "tight-target", el, f"{w:g} x {h:g} px is small for a thumb on a {width:g} px screen")

        for value in {text, label, el.get("placeholder") or ""}:
            for pattern, what in PLACEHOLDER:
                if value and pattern.search(value):
                    add("block", "placeholder-text", el, f"{what}: {value[:60]!r}")
                    break
            else:
                continue
            break

    found += look_warnings(view, looks, name)
    return found


def space_of(box, least):
    """The area a target claims: its box, grown to least x least around its centre when it is smaller."""
    x, y, w, h = box.get("x", 0), box.get("y", 0), box.get("width", 0), box.get("height", 0)
    gw, gh = max(w, least), max(h, least)
    return (x + w / 2 - gw / 2, y + h / 2 - gh / 2, x + w / 2 + gw / 2, y + h / 2 + gh / 2)


def overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def size_of(el):
    return el.get("fontSize") or 0


def look_warnings(view, looks, name):
    """Traits of a generic default look. Taste only: these never block."""
    out = []

    def warn(rule, selector, detail):
        out.append({"level": "warn", "rule": rule, "view": name, "selector": selector, "text": "", "detail": detail})

    texts = [e for e in view["elements"] if (e.get("text") or "").strip() and not e.get("visuallyHidden")]
    families = {re.split(r",", e.get("fontFamily") or "")[0].strip().strip("\"'").lower() for e in texts} - {""}
    common = {f.lower() for f in looks["default_font_families"]}
    if families and families <= common:
        warn("default-font", "html", f"all text uses {', '.join(sorted(families))}, a family most generated pages share")
    sizes = sorted({e.get("fontSize") for e in texts if e.get("fontSize")})
    if len(sizes) > looks["max_font_sizes"]:
        warn("many-sizes", "html", f"{len(sizes)} different text sizes in one view ({', '.join(f'{s:g}' for s in sizes)}); a type scale has fewer")
    for el in view["elements"]:
        role = el.get("role") or ""
        if role in ("button", "link", "heading", "tab") and EMOJI.search((el.get("text") or "") + (el.get("name") or "")):
            warn("emoji-icon", el.get("selector", "?"), "an emoji stands in for an icon")
        gradient = el.get("backgroundImage") or ""
        if "gradient" in gradient:
            hues = []
            for m in re.finditer(r"rgba?\([^()]*\)|#[0-9a-fA-F]{6}\b", gradient):
                colour = parse_colour(m.group(0))
                if colour:
                    h, _, s = colorsys.rgb_to_hls(*(c / 255 for c in colour[:3]))
                    if s > 0.35:
                        hues.append(h * 360)
            low, high = looks["default_gradient_hue_range"]
            if any(low <= h <= high for h in hues):
                warn("default-gradient", el.get("selector", "?"), "a violet-to-blue gradient, the most common generated accent")
    return out


def load_waivers(path):
    data = load_json(path)
    if not isinstance(data, list):
        raise BadInput(f"{path} must hold a JSON list of waivers")
    for entry in data:
        if not isinstance(entry, dict) or not entry.get("rule") or not entry.get("selector"):
            raise BadInput(f"{path}: a waiver needs rule and selector: {json.dumps(entry)}")
        if len(str(entry.get("reason", "")).strip()) < 8:
            raise BadInput(f"{path}: a waiver needs a reason of at least 8 characters: {json.dumps(entry)}")
    return data


def cmd_check(args):
    limits, unverified_limits, _ = load_data(LIMITS)
    looks, _, looks_raw = load_data(LOOKS)
    try:
        views = views_of(load_json(args.snapshot), args.snapshot)
        waivers = load_waivers(args.waivers) if args.waivers else []
        if args.report and pathlib.Path(args.report).exists():
            raise BadInput(f"{args.report} already exists and this script does not overwrite files")
    except BadInput as exc:
        print(str(exc))
        print(f"RESULT not verified: {exc}")
        return 2
    if unverified_limits:
        print(f"note: these limits were written from memory and not checked against the source: {', '.join(unverified_limits)} (see references/limits.json)")
    missing = []
    if not views:
        missing.append("the snapshot holds no views")
    for view in views:
        if not view["elements"]:
            missing.append(f"view {label_of(view)} holds no elements: not a capture of a page")
    widths = [int(w) for w in args.widths.split(",") if w.strip()] if args.widths is not None else [int(w) for w in limits["required_widths"]]
    themes = [t.strip() for t in args.themes.split(",") if t.strip()] if args.themes else []
    states = [s.strip() for s in args.states.split(",") if s.strip()] if args.states else []
    have = {(int(v["viewport"]["width"]), v.get("theme", "light"), v.get("state", "default")) for v in views}
    for w in widths:
        for t in themes or [None]:
            for s in states or [None]:
                if not any(hw == w and (t is None or ht == t) and (s is None or hs == s) for hw, ht, hs in have):
                    missing.append(f"no view at {w} px" + (f", theme {t}" if t else "") + (f", state {s}" if s else ""))
    findings, used = [], set()
    for view in views:
        findings += check_view(view, limits, looks)
    for f in findings:
        if f["level"] == "warn":
            continue
        for i, w in enumerate(waivers):
            if w["rule"] == f["rule"] and fnmatch.fnmatch(f["selector"], w["selector"]) and w.get("view", f["view"]) == f["view"]:
                f["level"], f["waived"] = "waived", w["reason"]
                used.add(i)
                break
    order = {"block": 0, "unverified": 1, "waived": 2, "warn": 3}
    tag = {"block": "BLOCK", "unverified": "CHECK", "waived": "waived", "warn": "warn"}
    for view in views:
        mine = sorted((f for f in findings if f["view"] == label_of(view)), key=lambda f: order[f["level"]])
        print(f"view {label_of(view)}: {len(view['elements'])} elements, {sum(f['level'] == 'block' for f in mine)} blocking, "
              f"{sum(f['level'] == 'unverified' for f in mine)} to check by eye, {sum(f['level'] == 'warn' for f in mine)} warnings")
        for f in mine[:args.max_lines]:
            quote = f"  \"{f['text']}\"" if f["text"] else ""
            extra = f"  [waived: {f['waived']}]" if f.get("waived") else ""
            print(f"  {tag[f['level']]:6} {f['rule']:16} {f['selector']}{quote}: {f['detail']}{extra}")
        if len(mine) > args.max_lines:
            print(f"  ... {len(mine) - args.max_lines} more in this view; pass --report <new file> for all of them")
    for i, w in enumerate(waivers):
        if i not in used:
            print(f"note: waiver matched nothing and can be removed: {json.dumps(w)}")
    for line in missing:
        print("missing: " + line)
    blocks = [f for f in findings if f["level"] == "block"]
    unsure = [f for f in findings if f["level"] == "unverified"]
    warns = [f for f in findings if f["level"] == "warn"]
    print(f"checked {len(views)} view(s): {len(blocks)} blocking, {len(unsure)} to check by eye, {len(used)} waived, {len(warns)} warnings")
    if warns:
        print(f"warnings are taste, not defects; the list of default looks was written on {looks_raw.get('_written', 'an unknown date')} and ages")
    print("not seen by this check: focus order and focus rings (a11y-audit), states that were not captured, motion, and whether the layout is what was asked for")
    if args.report:
        pathlib.Path(args.report).write_text(json.dumps({"snapshot": str(args.snapshot), "findings": findings, "missing": missing}, indent=2) + "\n", encoding="utf-8")
        print(f"report written to {args.report}")
    if blocks:
        rules = sorted({f["rule"] for f in blocks})
        print(f"RESULT fail: {len(blocks)} blocking finding(s): {', '.join(rules)}")
        return 1
    if missing or unsure:
        parts = missing[:3] + ([f"{len(unsure)} element(s) could not be judged"] if unsure else [])
        print(f"RESULT not verified: {'; '.join(parts)}")
        return 2
    print("RESULT pass")
    return 0


def cmd_merge(args):
    out = pathlib.Path(args.out)
    if out.exists():
        print(f"{out} already exists and this script does not overwrite files; give a new name")
        print("RESULT not verified: nothing merged")
        return 2
    views, seen = [], {}
    try:
        for path in args.views:
            for view in views_of(load_json(path), path):
                name = label_of(view)
                if name in seen:
                    raise BadInput(f"{path} and {seen[name]} both hold view {name}; label a capture with window.__mstackView before collecting")
                seen[name] = path
                views.append(view)
    except BadInput as exc:
        print(str(exc))
        print(f"RESULT not verified: {exc}")
        return 2
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"mstack_snapshot": 1, "views": views}, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {out} with {len(views)} view(s): {', '.join(seen)}")
    print("RESULT pass")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("merge", help="join captured views into one snapshot file")
    p.add_argument("views", nargs="+", help="JSON files returned by collect.js, one view each")
    p.add_argument("--out", required=True, help="new snapshot file to write")
    p = sub.add_parser("check", help="judge a snapshot")
    p.add_argument("snapshot", help="snapshot JSON (format 1)")
    p.add_argument("--widths", help="viewport widths that have to be present, comma-separated (default from references/limits.json; empty string for none)")
    p.add_argument("--themes", help="themes that have to be present at each width, for example light,dark")
    p.add_argument("--states", help="states that have to be present at each width, for example default,empty,error")
    p.add_argument("--waivers", help="JSON list of waivers: rule, selector (wildcards allowed), optional view, reason")
    p.add_argument("--report", help="write every finding to this new JSON file")
    p.add_argument("--max-lines", type=int, default=40, help="findings printed per view (default 40)")
    args = parser.parse_args()
    return {"merge": cmd_merge, "check": cmd_check}[args.action](args)


if __name__ == "__main__":
    sys.exit(main())

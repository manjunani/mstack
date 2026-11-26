#!/usr/bin/env python3
"""Lint the source of a screen for unfinished work and default-look traits, and count render rounds.

  lint   scan source files. Unfinished work blocks: filler Latin, TODO and FIXME markers in
         markup or styles, placeholder copy, invented proof (a testimonial or a number with
         no source), handlers that do nothing, links to nowhere, focus outlines removed with
         nothing in their place, stand-in names (Acme, John Doe, Your Company), stock
         placeholder images and links to example.com. Default-look traits only warn: line
         patterns and per-file checks (centred text, repeated card classes, icon-tile grids,
         same-length card copy, too many font weights, skipped heading levels) come from a
         dated list in references/default-looks.json, and a brief that asks for one wins.
  round  record one render-and-inspect round in .mstack/ui-build/rounds.json; the fourth
         round is refused, so the work stops and remaining issues go to the user.

Exit codes: 0 = no blocking finding (warnings may remain) / round recorded
            1 = at least one blocking finding
            2 = not verified or blocked: no source files, bad input, or the round limit reached
This script reads source files. Only `round` writes, and only under .mstack/ui-build/.
"""
import argparse
import datetime
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
LOOKS = HERE.parent / "references" / "default-looks.json"
SOURCE_EXT = {".html", ".htm", ".jsx", ".tsx", ".js", ".ts", ".vue", ".svelte", ".astro", ".css", ".scss"}
SKIP_DIRS = {"node_modules", ".git", "dist", "build", ".next", "out", "coverage", "vendor", ".mstack", ".testrun", "__pycache__"}
BLOCKS = [
    ("filler-text", re.compile(r"lorem ipsum|dolor sit amet|consectetur adipisc", re.I), "filler Latin is still in the screen"),
    ("placeholder-copy", re.compile(r"\b(placeholder|dummy|sample) (text|copy|title|heading|content)\b|\b(your|insert) [\w ]{0,20}\bhere\b|\bgoes here\b", re.I), "placeholder copy"),
    ("dead-handler", re.compile(r"on[A-Z]\w*=\{\s*\(\)\s*=>\s*\{\s*\}\s*\}|onclick=\"\s*\"|@click=\"\s*\"|on:click=\{\(\)\s*=>\s*\{\}\}"), "a handler that does nothing"),
    ("dead-link", re.compile(r"""href\s*=\s*["'](#|javascript:void\(0\);?)["']"""), "a link that goes nowhere"),
    ("placeholder-image", re.compile(r"\b(via\.placeholder\.com|placehold\.(co|it)|placeholder\.com|dummyimage\.com|picsum\.photos|placekitten\.com|placeimg\.com|loremflickr\.com|i\.pravatar\.cc|randomuser\.me/api/portraits|ui-avatars\.com)\b", re.I), "a stock placeholder image or fake avatar service"),
    ("example-link", re.compile(r"""\b(href|src|action)\s*=\s*\{?\s*["'`](https?://(www\.)?example\.(com|org|net)\b|mailto:[^"'`]*@example\.(com|org|net))""", re.I), "a link or address that still points to example.com"),
    ("invented-proof", re.compile(r"\b(trusted by|loved by|used by|join) (over |more than )?[\d,.]+\s*[kKmM+]*\+?\s*(teams|users|customers|companies|developers|people)\b|\b\d(\.\d)?/5 (stars|rating)\b|\b\d{2,3}% (faster|more|less|of (users|customers))\b", re.I), "a claim of proof (users, ratings, percentages); keep it only if the user supplied it"),
]
FOCUS_OFF = re.compile(r"outline\s*:\s*(none|0)\b|\boutline-none\b|focus:outline-none")
FOCUS_BACK = re.compile(r"focus-visible|:focus[^{]*\{[^}]*(box-shadow|outline\s*:\s*\d|border|ring)|focus:ring|focus-visible:ring|focus:shadow|focus:border")
PLACEHOLDER_NAME = re.compile(r"\b(Acme( (Inc|Corp|Co|Corporation|Ltd))?\.?|John Doe|Jane Doe|John Smith|Your (Company|Brand|Logo|Name)|Company Name|Brand ?Name|Product Name)\b")
# a hint inside an input's placeholder is a legitimate use of a sample name
PLACEHOLDER_ATTR = re.compile(r"""placeholder\s*[=:]\s*\{?\s*(["'`])[^"'`]*\1""", re.I)
MARKER = re.compile(r"(<!--|/\*|//|\{/\*)\s*(TODO|FIXME|XXX|HACK)\b|\b(TODO|FIXME)\s*:")


MARKUP_EXT = {".html", ".htm", ".jsx", ".tsx", ".js", ".ts", ".vue", ".svelte", ".astro"}
CLASS_ATTR = re.compile(r"""\bclass(?:Name)?\s*=\s*\{?\s*["'`]([^"'`]+)["'`]""")
CENTRED = re.compile(r"""\btext-center\b|text-align\s*:\s*center\b|textAlign\s*:\s*["']center""")
OTHER_ALIGN = re.compile(r"""\btext-(left|start|right|end|justify)\b|text-align\s*:\s*(left|start|right|end|justify)\b|textAlign\s*:\s*["'](left|start|right|end|justify)""")
WEIGHT_CLASS = {"thin": 100, "extralight": 200, "light": 300, "normal": 400, "medium": 500, "semibold": 600, "bold": 700, "extrabold": 800, "black": 900}
WEIGHT_TW = re.compile(r"(?<![\w-])font-(thin|extralight|light|normal|medium|semibold|bold|extrabold|black)(?![\w-])")
WEIGHT_CSS = re.compile(r"""font-?[wW]eight\s*:\s*["']?(\d00|bold|normal)\b""")
HEADING = re.compile(r"<h([1-6])\b")
H3_TEXT = re.compile(r"<h3\b[^>]*>(.*?)</h3>")
P_TEXT = re.compile(r"<p\b[^>]*>(.*?)</p>")
TAGS = re.compile(r"<[^>]+>|\{[^}]*\}")


def file_checks(path, lines, checks):
    """Per-file default-look checks that need counts across lines. Returns (id, line, what, shown line)."""
    out = []
    markup = path.suffix.lower() in MARKUP_EXT

    def add(rule, number, extra):
        out.append((rule, number, f"{checks[rule]['what']} ({extra})", lines[number - 1].strip()[:90]))

    c = checks["centred-everything"]
    centred = [i for i, line in enumerate(lines, 1) for _ in CENTRED.finditer(line)]
    other = sum(len(OTHER_ALIGN.findall(line)) for line in lines)
    if len(centred) >= c["min_centred"] and len(centred) / (len(centred) + other) >= c["min_share"]:
        add("centred-everything", centred[0], f"{len(centred)} centred, {other} other alignments")

    if markup:
        c = checks["same-card-everywhere"]
        seen = {}
        for i, line in enumerate(lines, 1):
            for value in CLASS_ATTR.findall(line):
                tokens = value.split()
                if any(t.startswith("rounded") for t in tokens) and any(t.startswith("shadow") and t != "shadow-none" for t in tokens):
                    seen.setdefault(" ".join(sorted(tokens)), []).append(i)
        repeats = sorted((places for places in seen.values() if len(places) >= c["min_repeats"]), key=len, reverse=True)
        if repeats:
            add("same-card-everywhere", repeats[0][0], f"{len(repeats[0])} blocks share one class list")

        c = checks["icon-tile-grid"]
        tiles = []
        for i, line in enumerate(lines, 1):
            for value in CLASS_ATTR.findall(line):
                tokens = set(value.split())
                square = any(f"h-{n}" in tokens and f"w-{n}" in tokens for n in ("8", "9", "10", "11", "12", "14", "16")) or any(f"size-{n}" in tokens for n in ("8", "9", "10", "11", "12", "14", "16"))
                if square and any(t.startswith("rounded") for t in tokens) and any(t.startswith("bg-") for t in tokens):
                    ahead = "\n".join(lines[i - 1:i + c["look_ahead_lines"]])
                    if re.search(r"<(h[2-6]|CardTitle)\b", ahead):
                        tiles.append(i)
                    break
        if len(tiles) >= c["min_tiles"]:
            add("icon-tile-grid", tiles[0], f"{len(tiles)} tiles")

        c = checks["uniform-card-copy"]
        cards = []
        for i, line in enumerate(lines, 1):
            title = H3_TEXT.search(line)
            if not title:
                continue
            for j in range(i - 1, min(len(lines), i + 3)):
                body = P_TEXT.search(lines[j] if j != i - 1 else line[title.end():])
                if body:
                    cards.append((i, len(TAGS.sub("", title.group(1)).split()), len(TAGS.sub("", body.group(1)).strip())))
                    break
        n = c["min_cards"]
        for k in range(len(cards) - n + 1):
            run = cards[k:k + n]
            lengths = [length for _, _, length in run]
            if len({words for _, words, _ in run}) == 1 and min(lengths) > 0 and max(lengths) / min(lengths) <= c["max_length_ratio"]:
                add("uniform-card-copy", run[0][0], f"{n} cards, texts of {min(lengths)} to {max(lengths)} characters")
                break

        levels = [(i, int(m.group(1))) for i, line in enumerate(lines, 1) for m in HEADING.finditer(line)]
        for (_, before), (i, level) in zip(levels, levels[1:]):
            if level > before + 1:
                add("skipped-heading", i, f"h{before} then h{level}")
                break

    c = checks["font-weight-sprawl"]
    weights = {}
    for i, line in enumerate(lines, 1):
        for name in WEIGHT_TW.findall(line):
            weights.setdefault(WEIGHT_CLASS[name], i)
        for value in WEIGHT_CSS.findall(line):
            weights.setdefault({"bold": 700, "normal": 400}.get(value) or int(value), i)
    if len(weights) > c["max_weights"]:
        add("font-weight-sprawl", min(weights.values()), f"{len(weights)} weights: {', '.join(str(w) for w in sorted(weights))}")
    return out


def files_under(root):
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in SOURCE_EXT and ".min." not in path.name:
            if not any(part in SKIP_DIRS for part in path.relative_to(root).parts[:-1]):
                yield path


def cmd_lint(args):
    root = pathlib.Path(args.path)
    if not root.exists():
        print(f"RESULT not verified: {root} does not exist")
        return 2
    files = [root] if root.is_file() else list(files_under(root))
    if not files:
        print(f"RESULT not verified: no source files under {root}")
        return 2
    data = json.loads(LOOKS.read_text(encoding="utf-8"))
    looks = data["patterns"]["value"]
    checks = data["file_checks"]["value"]
    findings = []
    for path in files:
        rel = path.name if root.is_file() else str(path.relative_to(root))
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        for number, line in enumerate(lines, 1):
            for rule, pattern, what in BLOCKS:
                if pattern.search(line):
                    findings.append(("block", rule, rel, number, what, line.strip()[:90]))
            if PLACEHOLDER_NAME.search(PLACEHOLDER_ATTR.sub("", line)):
                findings.append(("block", "placeholder-name", rel, number, "a stand-in name (Acme, John Doe, Your Company): use the real one or mark it as a listed placeholder", line.strip()[:90]))
            if MARKER.search(line):
                findings.append(("block", "work-marker", rel, number, "a TODO or FIXME marker: finish it or move it to the issue tracker", line.strip()[:90]))
            if FOCUS_OFF.search(line):
                window = "\n".join(lines[max(0, number - 6):number + 6])
                if not FOCUS_BACK.search(window) and not FOCUS_BACK.search(text):
                    findings.append(("block", "focus-removed", rel, number, "the focus outline is removed and no other focus style is given", line.strip()[:90]))
        for look in looks:
            hits = [i for i, line in enumerate(lines, 1) if re.search(look["pattern"], line, re.I)]
            if hits and len(hits) >= look.get("min", 1):
                findings.append(("warn", look["id"], rel, hits[0], f"{look['what']} ({len(hits)} place(s))", lines[hits[0] - 1].strip()[:90]))
        for rule, number, what, shown in file_checks(path, lines, checks):
            findings.append(("warn", rule, rel, number, what, shown))
    findings.sort(key=lambda f: (f[0] != "block", f[2], f[3]))
    for level, rule, rel, number, what, line in findings[:args.max_lines]:
        print(f"{'BLOCK' if level == 'block' else 'warn '} {rule:18} {rel}:{number}: {what}\n        {line}")
    if len(findings) > args.max_lines:
        print(f"... {len(findings) - args.max_lines} more")
    blocks = [f for f in findings if f[0] == "block"]
    warns = len(findings) - len(blocks)
    print(f"scanned {len(files)} file(s): {len(blocks)} blocking, {warns} default-look warnings (list written {data.get('_written', '?')}; taste, never blocking)")
    print("not seen by this check: how the screen looks when rendered; run the render step and design-review")
    if blocks:
        print(f"RESULT fail: {len(blocks)} unfinished item(s): {', '.join(sorted({f[1] for f in blocks}))}")
        return 1
    print("RESULT pass")
    return 0


def cmd_round(args):
    state = pathlib.Path(args.root) / ".mstack" / "ui-build"
    ledger = state / "rounds.json"
    rounds = json.loads(ledger.read_text(encoding="utf-8")) if ledger.exists() else []
    limit = json.loads(LOOKS.read_text(encoding="utf-8"))["max_rounds"]["value"]
    if len(rounds) >= limit:
        print(f"{len(rounds)} rounds already recorded in {ledger}")
        print(f"blocked: the limit of {limit} render rounds is reached; list what is still wrong and ask the user how to go on")
        return 2
    if len(args.note.strip()) < 8:
        print("RESULT not verified: --note has to say what was looked at and what was found (8 characters or more)")
        return 2
    state.mkdir(parents=True, exist_ok=True)
    rounds.append({"round": len(rounds) + 1, "when": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                   "screenshots": args.screenshot, "note": args.note})
    ledger.write_text(json.dumps(rounds, indent=2) + "\n", encoding="utf-8")
    missing = [s for s in args.screenshot if not pathlib.Path(s).is_file()]
    if missing:
        print(f"note: these screenshots do not exist: {', '.join(missing)}")
    print(f"round {len(rounds)} of {limit} recorded in {ledger}")
    print("RESULT pass")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("lint", help="scan source for unfinished work and default looks")
    p.add_argument("path", help="a source file or folder")
    p.add_argument("--max-lines", type=int, default=50, help="findings to print (default 50)")
    p = sub.add_parser("round", help="record one render-and-inspect round")
    p.add_argument("--note", required=True, help="what was looked at and found in this round")
    p.add_argument("--screenshot", action="append", default=[], help="screenshot file of this round (repeatable)")
    p.add_argument("--root", default=".", help="project folder (default: current folder)")
    args = parser.parse_args()
    return {"lint": cmd_lint, "round": cmd_round}[args.action](args)


if __name__ == "__main__":
    sys.exit(main())

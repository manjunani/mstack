#!/usr/bin/env python3
"""Lint the source of a screen for unfinished work and default-look traits, and count render rounds.

  lint   scan source files. Unfinished work blocks: filler Latin, TODO and FIXME markers in
         markup or styles, placeholder copy, invented proof (a testimonial or a number with
         no source), handlers that do nothing, links to nowhere, focus outlines removed with
         nothing in their place. Default-look traits only warn: they come from a dated list
         in references/default-looks.json, and a brief that asks for one of them wins.
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
    ("invented-proof", re.compile(r"\b(trusted by|loved by|used by|join) (over |more than )?[\d,.]+\s*[kKmM+]*\+?\s*(teams|users|customers|companies|developers|people)\b|\b\d(\.\d)?/5 (stars|rating)\b|\b\d{2,3}% (faster|more|less|of (users|customers))\b", re.I), "a claim of proof (users, ratings, percentages); keep it only if the user supplied it"),
]
FOCUS_OFF = re.compile(r"outline\s*:\s*(none|0)\b|\boutline-none\b|focus:outline-none")
FOCUS_BACK = re.compile(r"focus-visible|:focus[^{]*\{[^}]*(box-shadow|outline\s*:\s*\d|border|ring)|focus:ring|focus-visible:ring|focus:shadow|focus:border")
MARKER = re.compile(r"(<!--|/\*|//|\{/\*)\s*(TODO|FIXME|XXX|HACK)\b|\b(TODO|FIXME)\s*:")


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
    findings = []
    for path in files:
        rel = path.name if root.is_file() else str(path.relative_to(root))
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        for number, line in enumerate(lines, 1):
            for rule, pattern, what in BLOCKS:
                if pattern.search(line):
                    findings.append(("block", rule, rel, number, what, line.strip()[:90]))
            if MARKER.search(line):
                findings.append(("block", "work-marker", rel, number, "a TODO or FIXME marker: finish it or move it to the issue tracker", line.strip()[:90]))
            if FOCUS_OFF.search(line):
                window = "\n".join(lines[max(0, number - 6):number + 6])
                if not FOCUS_BACK.search(window) and not FOCUS_BACK.search(text):
                    findings.append(("block", "focus-removed", rel, number, "the focus outline is removed and no other focus style is given", line.strip()[:90]))
        for look in looks:
            hits = [i for i, line in enumerate(lines, 1) if re.search(look["pattern"], line, re.I)]
            if hits:
                findings.append(("warn", look["id"], rel, hits[0], f"{look['what']} ({len(hits)} place(s))", lines[hits[0] - 1].strip()[:90]))
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

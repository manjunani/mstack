#!/usr/bin/env python3
"""Check research findings against their sources: exact quotes, people per theme, and what nobody cited.

  number FILE [FILE ...]   print each source with line numbers, to cite from
  template FILE            write an empty findings file (refuses if FILE exists)
  check FILE               check every quote, count people per theme, list uncited stretches

The findings file is JSON:
  threshold  fewest distinct participants a theme needs (default 3); below it, the finding is an anecdote
  sources    [{"file": "notes/p1.md", "participant": "P1"}]   one participant per source file
  themes     [{"id": "T-01", "title": "...", "claim": "one sentence", "label": "theme" or "anecdote",
               "evidence": [{"source": "notes/p1.md", "line": 14, "quote": "exact words"}]}]
             line may be a range "14-15" when the quote runs over a line break

What check enforces:
  - every source file exists under --root, and each has a participant
  - every quote appears word for word on its cited line or range (spacing and curly quotes are evened out; nothing else)
  - a quote found elsewhere in the source fails with the line where it really is
  - every theme reports its distinct participants; a theme with fewer than the threshold must be labelled "anecdote"
What check reports without failing:
  - an "anecdote" that has reached the threshold
  - per source: share of non-blank lines cited, and stretches of --gap or more non-blank lines that no finding cites

Exit codes: 0 = pass
            1 = fail: an unverified quote, or a theme labelled above its evidence
            2 = blocked: no file, not valid JSON, a missing source, or a finding with no evidence at all
The script reads the sources and writes nothing except the file given to template.
"""
import argparse
import json
import pathlib
import re
import sys

PLACEHOLDER = re.compile(r"\b(tbd|todo|fixme|to be decided|fill in)\b|\?\?\?|<[A-Za-z][^<>]{0,40}>", re.I)
SAME = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "–": "-", "—": "-", " ": " "})


def even(text):
    return re.sub(r"\s+", " ", str(text).translate(SAME)).strip().lower()


def said(value, least=3):
    return isinstance(value, str) and len(value.strip()) >= least and not PLACEHOLDER.search(value)


def span(line):
    """Return (first, last) line numbers from 14 or "14-15", or None."""
    if isinstance(line, int) and not isinstance(line, bool):
        return (line, line)
    match = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+))?\s*", str(line))
    if not match:
        return None
    first = int(match.group(1))
    last = int(match.group(2) or first)
    return (first, last) if last >= first else None


def cmd_number(args):
    missing = 0
    for path in args.files:
        if not path.is_file():
            print(f"blocked: {path} does not exist")
            missing += 1
            continue
        print(f"==> {path}")
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            print(f"{number:5}  {line}")
    return 2 if missing else 0


def cmd_template(args):
    if args.file.exists():
        print(f"blocked: {args.file} already exists; it is not overwritten")
        return 2
    data = {"threshold": 3, "sources": [{"file": "", "participant": ""}],
            "themes": [{"id": "T-01", "title": "", "claim": "", "label": "theme", "evidence": [{"source": "", "line": None, "quote": ""}]}]}
    args.file.parent.mkdir(parents=True, exist_ok=True)
    args.file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.file}: one empty source and one empty theme. check refuses it until filled in.")
    print("RESULT pass")
    return 0


def cmd_check(args):
    root = args.root.resolve()
    if not args.file.exists():
        print(f"blocked: {args.file} does not exist. Run: evidence.py template {args.file}")
        return 2
    try:
        data = json.loads(args.file.read_text(encoding="utf-8"))
    except ValueError as exc:
        print(f"blocked: {args.file} is not valid JSON ({exc})")
        return 2
    threshold = data.get("threshold", 3) if isinstance(data, dict) else None
    sources = data.get("sources") if isinstance(data, dict) and isinstance(data.get("sources"), list) else []
    themes = data.get("themes") if isinstance(data, dict) and isinstance(data.get("themes"), list) else []
    blocked = []
    if not isinstance(threshold, int) or isinstance(threshold, bool) or threshold < 2:
        blocked.append(f"threshold must be a whole number of at least 2; it is {threshold!r}")
    if not sources:
        blocked.append("no sources listed")
    if not themes:
        blocked.append("no themes listed")
    text, who = {}, {}
    for position, source in enumerate(sources, 1):
        name = source.get("file") if isinstance(source, dict) else None
        if not said(name, 1):
            blocked.append(f"source {position}: no file")
            continue
        path = (root / name).resolve()
        if not path.is_file() or not path.is_relative_to(root):
            blocked.append(f"source '{name}' is not a file under {root}")
            continue
        if not said(source.get("participant"), 1):
            blocked.append(f"source '{name}': no participant. Name who spoke (an id such as P1 is enough)")
        text[name] = path.read_text(encoding="utf-8", errors="replace").splitlines()
        who[name] = str(source.get("participant", "")).strip()
    for theme in themes:
        if not isinstance(theme, dict) or not isinstance(theme.get("evidence"), list) or not theme["evidence"]:
            blocked.append(f"{theme.get('id') if isinstance(theme, dict) else theme}: a finding with no evidence. Remove it or cite the lines it comes from")
    if blocked:
        for line in blocked:
            print("  BLOCKED  " + line)
        print(f"blocked: {len(blocked)} problem(s); no quote was checked")
        return 2

    problems, notes, cited = [], [], {name: set() for name in text}
    print(f"checking {args.file}: {len(themes)} findings, {len(text)} sources, threshold {threshold} participants\n")
    for theme in themes:
        tid = theme.get("id", "?")
        if not said(theme.get("claim"), 8):
            problems.append(f"{tid}: claim is empty or a placeholder")
        people, good, bad = set(), 0, 0
        for number, item in enumerate(theme["evidence"], 1):
            label = f"{tid} quote {number}"
            source, quote, where = item.get("source"), item.get("quote"), span(item.get("line"))
            if source not in text:
                problems.append(f"{label}: source '{source}' is not one of the listed sources")
                bad += 1
                continue
            if not said(quote, 4):
                problems.append(f"{label}: the quote is empty or a placeholder")
                bad += 1
                continue
            lines = text[source]
            if where is None or where[0] < 1 or where[1] > len(lines):
                problems.append(f"{label}: line {item.get('line')!r} is not a line of {source} ({len(lines)} lines)")
                bad += 1
                continue
            if even(quote) in even(" ".join(lines[where[0] - 1:where[1]])):
                good += 1
                people.add(who[source])
                cited[source].update(range(where[0], where[1] + 1))
                continue
            bad += 1
            single = [str(n) for n in range(1, len(lines) + 1) if even(quote) in even(lines[n - 1])]
            pairs = [f"{n}-{n + 1}" for n in range(1, len(lines)) if even(quote) in even(lines[n - 1] + " " + lines[n])]
            elsewhere = single or pairs
            if elsewhere:
                problems.append(f"{label}: not on line {item.get('line')} of {source}; it is at line {elsewhere[0]}")
            else:
                problems.append(f"{label}: not found word for word in {source}: \"{quote[:70]}\"")
        count = len(people)
        claimed = theme.get("label", "theme")
        state = "theme" if count >= threshold else "anecdote"
        print(f"  {tid}  {state:8} {count} participant(s) ({', '.join(sorted(people)) or 'none verified'}), {good} quote(s) verified"
              + (f", {bad} not" if bad else "") + f"  {theme.get('title', '')}")
        if claimed not in ("theme", "anecdote"):
            problems.append(f"{tid}: label must be 'theme' or 'anecdote'")
        elif claimed == "theme" and count < threshold:
            problems.append(f"{tid}: labelled a theme with {count} distinct participant(s) behind verified quotes; under {threshold} it is an anecdote")
        elif claimed == "anecdote" and count >= threshold:
            notes.append(f"{tid}: labelled an anecdote, and {count} participants support it; it may be a theme")

    print("\nCoverage (what no finding cites):")
    for name, lines in text.items():
        content = [n for n, line in enumerate(lines, 1) if line.strip()]
        share = 100 * len([n for n in content if n in cited[name]]) / len(content) if content else 0
        stretches, run = [], []
        for n in content + [None]:
            if n is not None and n not in cited[name] and (not run or n == run[-1] + 1 or all(not lines[k - 1].strip() for k in range(run[-1] + 1, n))):
                run.append(n)
                continue
            if len(run) >= args.gap:
                stretches.append((run[0], run[-1]))
            run = [n] if n is not None and n not in cited[name] else []
        print(f"  {name} ({who[name]}): {share:.0f}% of {len(content)} lines cited"
              + ("; uncited: " + ", ".join(f"lines {a}-{b}" for a, b in stretches) if stretches else ""))
    for line in notes:
        print("  note  " + line)
    for line in problems:
        print("  FAIL  " + line)
    if problems:
        print(f"RESULT fail: {len(problems)} problem(s) in the findings")
        return 1
    print("RESULT pass")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path.cwd(), help="folder the source paths are read from (default: current folder)")
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("number", help="print sources with line numbers")
    p.add_argument("files", nargs="+", type=pathlib.Path)
    p = sub.add_parser("template", help="write an empty findings file")
    p.add_argument("file", type=pathlib.Path)
    p = sub.add_parser("check", help="check quotes, counts and coverage")
    p.add_argument("file", type=pathlib.Path)
    p.add_argument("--gap", type=int, default=8, help="report uncited stretches of at least this many non-blank lines (default 8)")
    args = parser.parse_args()
    return {"number": cmd_number, "template": cmd_template, "check": cmd_check}[args.action](args)


if __name__ == "__main__":
    sys.exit(main())

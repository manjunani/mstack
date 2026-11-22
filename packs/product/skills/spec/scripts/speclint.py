#!/usr/bin/env python3
"""Lint a one-page spec, and list what existing code does so a spec can be written from it.

  template FILE --title T    write an empty spec to fill in (refuses if FILE exists)
  check FILE                 lint the spec
  check FILE --from-code     lint a spec written from existing code: every line must also cite its source file
  survey                     list routes, commands and tests found in the code, each with file:line

The spec is Markdown with these parts:

  # Spec: <title>
  ## Goal            one short paragraph: who gets what, and why
  ## Done when       one bullet per requirement, in this shape:
                       - R-001: <statement> Check: <method>: <how>
                     method is one of: test, command, measure, inspect, demo
                     a spec written from code adds:  Source: <path>[:line]
  ## Not doing       at least one bullet: what was left out on purpose
  ## Open questions  optional; must be empty or "none" before the spec passes

What check enforces:
  - the title and the three required parts are present and not empty
  - every "Done when" bullet starts with an id of the form R-001; ids are unique
  - every bullet names its check method and says how
  - no vague word (the list is references/vague-words.json) outside backticks or double quotes
  - no placeholder text anywhere (TBD, TODO, ???, <name>)
  - no open question left
  - with --from-code: every bullet has a Source, the file exists under --root and the line number is inside it
Warnings (shown, never failing): a statement joined with "and", a spec longer than --max-lines.

Exit codes: 0 = pass
            1 = fail: the lines say what is wrong and where
            2 = blocked or not verified: no file, no word list, nothing recognised by survey
This script reads files. The only file it writes is the one given to template.
"""
import argparse
import json
import os
import pathlib
import re
import sys

METHODS = ["test", "command", "measure", "inspect", "demo"]
REQUIRED = ["goal", "done when", "not doing"]
ID = re.compile(r"^R-\d{3,}$")
BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
LINE = re.compile(r"^(?P<id>\S+?):\s*(?P<statement>.*?)\s*\bCheck:\s*(?P<method>[A-Za-z]+)\s*[:,]?\s*(?P<how>.*?)\s*(?:\bSource:\s*(?P<source>.+?))?\s*$")
PLACEHOLDER = re.compile(r"\b(tbd|todo|fixme|lorem ipsum|to be decided|fill in)\b|\?\?\?|<[A-Za-z][^<>]{0,40}>", re.I)
SKIP_DIRS = {".git", ".mstack", ".testrun", "node_modules", "dist", "build", "target", "venv", ".venv", "__pycache__", "vendor", ".next"}
CODE_EXT = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".go", ".rs", ".rb", ".java", ".kt", ".swift", ".php", ".cs"}
SURVEY = [
    ("route", re.compile(r"@\w+\.(get|post|put|patch|delete|route)\(\s*[\"']([^\"']+)")),
    ("route", re.compile(r"\b(?:app|router|api)\.(get|post|put|patch|delete)\(\s*[\"'`]([^\"'`]+)")),
    ("command", re.compile(r"(add_parser)\(\s*[\"']([^\"']+)")),
    ("command", re.compile(r"\.(command)\(\s*[\"']([^\"']+)")),
    ("option", re.compile(r"(add_argument)\(\s*[\"'](--[\w-]+)")),
    ("command", re.compile(r"#\[(tauri)::(command)")),
    ("test", re.compile(r"^\s*(?:async\s+)?(def)\s+(test_\w+)")),
    ("test", re.compile(r"^\s*(it|test)\(\s*[\"'`]([^\"'`]+)")),
    ("test", re.compile(r"^(func)\s+(Test\w+)")),
]


def strip_literals(text):
    """Remove backtick spans and double-quoted spans: they hold names and literal values, not prose."""
    return re.sub(r"`[^`]*`|\"[^\"]*\"|“[^”]*”", " ", text)


def load_words():
    path = pathlib.Path(__file__).resolve().parent.parent / "references" / "vague-words.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [w.lower() for w in data["words"]], [p.lower() for p in data["phrases"]]
    except (OSError, ValueError, KeyError) as exc:
        print(f"blocked: the vague-word list could not be read ({path}: {exc})")
        return None


def sections(lines):
    """Return (title, {heading lower: [(line number, text)]})."""
    title, parts, current = None, {}, None
    for number, line in enumerate(lines, 1):
        if line.startswith("# ") and title is None:
            title = line[2:].strip()
        elif line.startswith("## "):
            current = line[3:].strip().lower()
            parts[current] = []
        elif current is not None:
            parts[current].append((number, line))
    return title, parts


def bullets(rows):
    """Join each bullet with its indented continuation lines. Return [(line number, text)]."""
    found = []
    for number, line in rows:
        match = BULLET.match(line)
        if match:
            found.append([number, match.group(1).strip()])
        elif found and line.strip() and line.startswith((" ", "\t")):
            found[-1][1] += " " + line.strip()
    return [(n, t) for n, t in found]


def walk(root):
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(files):
            path = pathlib.Path(folder) / name
            if path.suffix in CODE_EXT:
                yield path


def survey(root):
    found = []
    for path in walk(root):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            for kind, pattern in SURVEY:
                match = pattern.search(line)
                if match:
                    found.append((kind, f"{match.group(1)} {match.group(2)}", str(path.relative_to(root)), number))
                    break
    return found


def cmd_template(args):
    if args.file.exists():
        print(f"blocked: {args.file} already exists; it is not overwritten")
        return 2
    args.file.parent.mkdir(parents=True, exist_ok=True)
    args.file.write_text(
        f"# Spec: {args.title}\n\n## Goal\n\n\n## Done when\n\n- R-001: \n\n## Not doing\n\n\n## Open questions\n\n- none\n",
        encoding="utf-8")
    print(f"wrote {args.file}: empty parts and one empty requirement. It fails check until filled in.")
    print("RESULT pass")
    return 0


def cmd_survey(args):
    root = args.root.resolve()
    found = survey(root)
    for kind, what, path, number in found:
        print(f"  {kind:8} {what:44} {path}:{number}")
    counts = {k: sum(1 for f in found if f[0] == k) for k in ("route", "command", "option", "test")}
    print("survey of " + str(root) + ": " + ", ".join(f"{n} {k}s" for k, n in counts.items()))
    if not found:
        print("RESULT not verified: no route, command or test was recognised. Read the code by hand and cite the files you read")
        return 2
    print("These are places to read, not requirements. Write a line only for behaviour you read in the file you cite.")
    print("RESULT pass")
    return 0


def cmd_check(args):
    if not args.file.exists():
        print(f"blocked: {args.file} does not exist")
        return 2
    words = load_words()
    if words is None:
        return 2
    vague_words, vague_phrases = words
    root = args.root.resolve()
    text = args.file.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    title, parts = sections(lines)
    problems, warnings = [], []

    if not title or not strip_literals(re.sub(r"^spec:\s*", "", title, flags=re.I)).strip():
        problems.append("line 1: no title. Start with '# Spec: <what this is>'")
    for part in REQUIRED:
        if part not in parts:
            problems.append(f"missing part '## {part.capitalize()}'")
        elif not any(line.strip() for _, line in parts[part]):
            problems.append(f"part '## {part.capitalize()}' is empty")
    for number, line in enumerate(lines, 1):
        hit = PLACEHOLDER.search(strip_literals(line))
        if hit:
            problems.append(f"line {number}: placeholder '{hit.group(0)}'")

    ids, cited = {}, set()
    for number, item in bullets(parts.get("done when", [])):
        match = LINE.match(item)
        head = item.split(":", 1)[0].strip()
        if not ID.match(head):
            problems.append(f"line {number}: starts with '{head[:20]}', not an id of the form R-001")
            continue
        if head in ids:
            problems.append(f"line {number}: {head} is already used on line {ids[head]}")
        ids.setdefault(head, number)
        if not match:
            problems.append(f"line {number}: {head} does not name its check. Add 'Check: <method>: <how>' ({', '.join(METHODS)})")
            continue
        statement, method, how, source = match.group("statement"), match.group("method").lower(), match.group("how"), match.group("source")
        if not statement.strip(" ."):
            problems.append(f"line {number}: {head} has no statement")
        if method not in METHODS:
            problems.append(f"line {number}: {head} uses check method '{method}'. Use one of: {', '.join(METHODS)}")
        if not how.strip(" ."):
            problems.append(f"line {number}: {head} names the method '{method}' and not how: which test, command, number, thing to look at or steps")
        plain = " " + re.sub(r"[^a-z0-9/'-]+", " ", strip_literals(statement).lower()) + " "
        for word in vague_words:
            if f" {word} " in plain:
                problems.append(f"line {number}: {head} uses '{word}', which cannot be checked. Say what is observed, with a number where there is one")
        for phrase in vague_phrases:
            if f" {phrase} " in plain:
                problems.append(f"line {number}: {head} uses '{phrase}', which leaves the requirement open-ended")
        if re.search(r"\band\b", strip_literals(statement), re.I):
            warnings.append(f"line {number}: {head} joins two things with 'and'. If either can fail alone, give each its own id")
        if args.from_code:
            if not source:
                problems.append(f"line {number}: {head} cites no file. Add 'Source: <path>:<line>' for the code it was read from")
            for where in ([s.strip().strip("`. ") for s in source.split(",")] if source else []):
                found = re.match(r"^(.*?)(?::(\d+))?$", where)
                path = (root / found.group(1)).resolve()
                if not where or not path.is_file() or not path.is_relative_to(root):
                    problems.append(f"line {number}: {head} cites '{where}', which is not a file under {root}")
                else:
                    cited.add(str(path.relative_to(root)))
                    if found.group(2):
                        length = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
                        if not 1 <= int(found.group(2)) <= length:
                            problems.append(f"line {number}: {head} cites line {found.group(2)} of {found.group(1)}, which has {length} lines")
    if "done when" in parts and not ids and not any("R-001" in p for p in problems):
        problems.append("part '## Done when' has no requirement bullet")
    if "not doing" in parts and any(l.strip() for _, l in parts["not doing"]) and not bullets(parts["not doing"]):
        problems.append("part '## Not doing' needs at least one bullet")
    for number, item in bullets(parts.get("open questions", [])):
        if item.strip(" .").lower() not in ("none", "none left", ""):
            problems.append(f"line {number}: open question left: {item[:70]}")
    if len(lines) > args.max_lines:
        warnings.append(f"the spec is {len(lines)} lines; one page is about {args.max_lines}. Move detail out or cut scope")
    if args.from_code:
        entry_files = sorted({path for kind, _, path, _ in survey(root) if kind in ("route", "command")} - cited)
        if entry_files:
            warnings.append("routes or commands in files that no requirement cites: " + ", ".join(entry_files[:8])
                            + (" ..." if len(entry_files) > 8 else ""))

    numbers = sorted(int(i[2:]) for i in ids)
    mode = "written from code" if args.from_code else "new work"
    print(f"checked {args.file} ({mode}): {len(ids)} requirements, {len(lines)} lines"
          + (f"; next free id R-{numbers[-1] + 1:03d}" if numbers else ""))
    for line in warnings:
        print("  warn  " + line)
    for line in problems:
        print("  FAIL  " + line)
    if problems:
        print(f"RESULT fail: {len(problems)} problem(s) in the spec")
        return 1
    print("RESULT pass")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path.cwd(), help="project folder (default: current folder)")
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("template", help="write an empty spec")
    p.add_argument("file", type=pathlib.Path)
    p.add_argument("--title", required=True)
    p = sub.add_parser("check", help="lint a spec")
    p.add_argument("file", type=pathlib.Path)
    p.add_argument("--from-code", action="store_true", help="the spec describes existing code: require a Source on every line")
    p.add_argument("--max-lines", type=int, default=80, help="warn above this many lines (default 80)")
    sub.add_parser("survey", help="list routes, commands and tests in the code with file:line")
    args = parser.parse_args()
    return {"template": cmd_template, "check": cmd_check, "survey": cmd_survey}[args.action](args)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Map each requirement id in a spec to the tests, code and commits that mention it.

  matrix                    read the ids, search the project, print and save the matrix
  waive ID --flag F --reason R
                            accept one "no-test" or "no-code" flag for one id, with a reason

Where ids are read from: the bullets of a spec that start with an id of the form R-001
(the "## Done when" part when the spec has one). Specs are found in docs/specs/*.md, SPEC.md,
spec.md and docs/spec.md, or given with --spec.

Where ids are searched for:
  tests    files in a test folder or named like a test (test_x.py, x_test.go, x.test.ts, x.spec.ts).
           The id may be written R-001, or R_001 / r_001 inside a test name.
  code     other source files, where the id is written R-001 (usually in a comment)
  commits  commit messages on the current branch; a commit counts as code evidence
           when it changed at least one source file that is not a test

The four flags:
  no-test       a requirement no test mentions (not raised when the spec says the check is
                command, measure, inspect or demo: no test is expected there)
  orphan-test   an id in a test that the spec does not define
  no-code       a requirement that no source file and no commit mentions
  gone          an id in source code that the spec does not define

Exit codes: 0 = pass: no flag, or every flag is waived with a reason
            1 = fail: at least one flag is not waived
            2 = blocked or not verified: no spec, no ids, or commit messages could not be searched
                (give --no-commits to accept a matrix built from files only)
The script reads the project and writes only .mstack/trace/ (matrix.md, matrix.json, waivers.json).
"""
import argparse
import datetime
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

STATE = pathlib.Path(".mstack") / "trace"
SKIP_DIRS = {".git", ".mstack", ".testrun", "node_modules", "dist", "build", "target", "venv", ".venv", "__pycache__", "vendor", ".next", "coverage"}
CODE_EXT = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".rs", ".rb", ".java", ".kt", ".swift", ".php", ".cs",
            ".c", ".h", ".cpp", ".hpp", ".sh", ".sql", ".vue", ".svelte", ".feature"}
TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs", "e2e", "integration", "features"}
TEST_NAME = re.compile(r"^(test_.*|.*_test|.*\.test|.*\.spec|.*Tests?|.*_spec)$")
DEFINED = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(R-\d{3,})\s*:\s*(.*)$")
MENTION = re.compile(r"(?<![A-Za-z0-9-])R-(\d{3,})(?![0-9])")
MENTION_IN_NAME = re.compile(r"(?<![A-Za-z0-9])[Rr]_(\d{3,})(?![0-9])")
METHOD = re.compile(r"\bCheck:\s*([A-Za-z]+)")
NO_TEST_EXPECTED = {"command", "measure", "inspect", "demo"}
WAIVABLE = ("no-test", "no-code")
PLACEHOLDER = re.compile(r"\b(tbd|todo|fixme|later|n/a)\b|\?\?\?", re.I)
MAX_BYTES = 2_000_000


def git(root, *args):
    try:
        out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout if out.returncode == 0 else None


def is_test(relative):
    parts = pathlib.PurePath(relative).parts
    if any(p.lower() in TEST_DIRS for p in parts[:-1]):
        return True
    return bool(TEST_NAME.match(pathlib.PurePath(relative).stem))


def is_code(relative):
    return pathlib.PurePath(relative).suffix in CODE_EXT


def find_specs(root, given):
    if given:
        return [(root / p).resolve() if not pathlib.Path(p).is_absolute() else pathlib.Path(p) for p in given]
    found = sorted((root / "docs" / "specs").glob("*.md")) if (root / "docs" / "specs").is_dir() else []
    for name in ("SPEC.md", "spec.md", "docs/spec.md"):
        if (root / name).is_file() and (root / name).resolve() not in [f.resolve() for f in found]:
            found.append(root / name)
    return found


def read_requirements(spec):
    """Return {id: {statement, method, line}} from one spec, and the ids defined twice."""
    lines = spec.read_text(encoding="utf-8", errors="replace").splitlines()
    has_part = any(l.strip().lower() == "## done when" for l in lines)
    inside, found, repeated = not has_part, {}, []
    for number, line in enumerate(lines, 1):
        if line.startswith("## "):
            inside = line.strip().lower() == "## done when" if has_part else True
            continue
        match = DEFINED.match(line) if inside else None
        if match:
            rid, rest = match.group(1), match.group(2)
            if rid in found:
                repeated.append(rid)
                continue
            method = METHOD.search(rest)
            found[rid] = {"statement": re.split(r"\s*\bCheck:", rest)[0].strip(), "method": method.group(1).lower() if method else None,
                          "line": number, "spec": spec.name, "continued": number}
        elif inside and found and line.startswith((" ", "\t")) and line.strip():
            last = next(reversed(found.values()))
            if last["continued"] == number - 1 and last["method"] is None:
                method = METHOD.search(line)
                last["method"] = method.group(1).lower() if method else None
                last["continued"] = number
    return found, repeated


def search_files(root, skip):
    """Return {id: {"tests": [path:line], "code": [path:line]}} for every id mentioned in tests or code."""
    hits = {}
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(files):
            path = pathlib.Path(folder) / name
            relative = str(path.relative_to(root))
            if path.resolve() in skip or not is_code(relative):
                continue
            try:
                if path.stat().st_size > MAX_BYTES:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            kind = "tests" if is_test(relative) else "code"
            for number, line in enumerate(text.splitlines(), 1):
                found = {f"R-{m}" for m in MENTION.findall(line)}
                if kind == "tests":
                    found |= {f"R-{m}" for m in MENTION_IN_NAME.findall(line)}
                for rid in sorted(found):
                    hits.setdefault(rid, {"tests": [], "code": []})[kind].append(f"{relative}:{number}")
    return hits


def search_commits(root):
    """Return {id: [{"hash", "code": bool}]} from commit messages, or None when git cannot answer."""
    if shutil.which("git") is None or git(root, "rev-parse", "--is-inside-work-tree") is None:
        return None
    log = git(root, "log", "--format=%x1e%h%x1f%B%x1f", "--name-only")
    if log is None:
        return {} if git(root, "rev-parse", "HEAD") is None else None
    found = {}
    for record in log.split("\x1e")[1:]:
        fields = record.split("\x1f")
        if len(fields) < 3:
            continue
        changed = [f for f in fields[2].splitlines() if f.strip()]
        touches_code = any(is_code(f) and not is_test(f) for f in changed)
        for rid in sorted({f"R-{m}" for m in MENTION.findall(fields[1])}):
            found.setdefault(rid, []).append({"hash": fields[0].strip(), "code": touches_code})
    return found


def spec_history(root, specs, rid):
    """Say whether an id that the spec does not define was ever in it."""
    for spec in specs:
        try:
            relative = str(spec.resolve().relative_to(root))
        except ValueError:
            continue
        out = git(root, "log", "--format=%h", f"-S{rid}", "--", relative)
        if out and out.strip():
            return f"was in {relative}; last changed there in commit {out.split()[0]}"
    return "never in the spec (a typing mistake, or an id from another document)"


def load_waivers(root):
    path = root / STATE / "waivers.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("waivers", [])
    except ValueError:
        return None


def short(items, limit=3):
    if not items:
        return "-"
    return ", ".join(items[:limit]) + (f" (+{len(items) - limit} more)" if len(items) > limit else "")


def cmd_matrix(root, args):
    specs = find_specs(root, args.spec)
    missing = [str(s) for s in specs if not s.is_file()]
    if not specs or missing:
        print("blocked: " + (f"spec not found: {', '.join(missing)}" if missing else
                             "no spec found in docs/specs/, SPEC.md, spec.md or docs/spec.md. Give --spec <file>"))
        return 2
    requirements, repeated = {}, []
    for spec in specs:
        found, twice = read_requirements(spec)
        repeated += twice + [rid for rid in found if rid in requirements]
        requirements.update({rid: info for rid, info in found.items() if rid not in requirements})
    if not requirements:
        print(f"blocked: no requirement id of the form R-001 in {', '.join(s.name for s in specs)}. Write the spec with ids first")
        return 2
    waivers = load_waivers(root)
    if waivers is None:
        print(f"blocked: {STATE / 'waivers.json'} is not valid JSON")
        return 2

    files = search_files(root, {s.resolve() for s in specs})
    commits = None if args.no_commits else search_commits(root)
    waived = {(w.get("id"), w.get("flag")): w.get("reason", "") for w in waivers}
    rows, flags, notes, undecided = [], [], [], []
    for rid in sorted(requirements, key=lambda r: int(r[2:])):
        info = requirements[rid]
        tests = files.get(rid, {}).get("tests", [])
        code = files.get(rid, {}).get("code", [])
        made = (commits or {}).get(rid, [])
        row_flags = []
        if not tests:
            if info["method"] in NO_TEST_EXPECTED:
                notes.append(f"{rid}: no test, and none expected (the spec's check is '{info['method']}')")
            else:
                row_flags.append("no-test")
        shown = []
        if not code and not any(c["code"] for c in made):
            if commits is None and not args.no_commits:
                undecided.append(rid)
                shown.append("no-code? (commits not searched)")
            else:
                row_flags.append("no-code")
        for flag in row_flags:
            if (rid, flag) in waived:
                shown.append(f"{flag} (waived: {waived[(rid, flag)]})")
            else:
                shown.append(flag)
                flags.append(f"{flag:12} {rid}: {info['statement'][:70]}")
        rows.append({"id": rid, "statement": info["statement"], "check": info["method"], "tests": tests, "code": code,
                     "commits": [c["hash"] for c in made], "flags": shown})
    for rid in sorted(set(files) - set(requirements), key=lambda r: int(r[2:])):
        history = spec_history(root, specs, rid)
        if files[rid]["tests"]:
            flags.append(f"{'orphan-test':12} {rid} in {short(files[rid]['tests'])}: {history}")
        if files[rid]["code"]:
            flags.append(f"{'gone':12} {rid} in {short(files[rid]['code'])}: {history}")
    for rid in repeated:
        flags.append(f"{'repeated-id':12} {rid} is defined more than once in the spec")
    for rid in sorted(set(commits or {}) - set(requirements) - set(files)):
        notes.append(f"{rid}: appears only in commit history ({short([c['hash'] for c in commits[rid]])}), not in the spec")
    for (rid, flag), reason in waived.items():
        row = next((r for r in rows if r["id"] == rid), None)
        if row is None or not any(f.startswith(flag) for f in row["flags"]):
            notes.append(f"waiver for {rid} ({flag}) no longer applies; remove it from {STATE / 'waivers.json'}")

    header = "| id | check | tests | code | commits | flags |\n|---|---|---|---|---|---|"
    table = [f"| {r['id']} | {r['check'] or '-'} | {short(r['tests'])} | {short(r['code'])} | {short(r['commits'])} | {'; '.join(r['flags']) or 'ok'} |" for r in rows]
    out_dir = root / STATE
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    commit_note = "not searched (--no-commits)" if args.no_commits else ("not searched: no git repository here" if commits is None else "searched")
    (out_dir / "matrix.md").write_text(
        f"# Trace matrix\n\nMade {stamp} from {', '.join(s.name for s in specs)}. Commit messages: {commit_note}.\n\n{header}\n"
        + "\n".join(table) + "\n\n## Flags\n\n" + ("\n".join(f"- {f}" for f in flags) or "- none") + "\n", encoding="utf-8")
    (out_dir / "matrix.json").write_text(json.dumps({"made": stamp, "specs": [s.name for s in specs], "commits": commit_note,
                                                    "rows": rows, "flags": flags, "notes": notes}, indent=2) + "\n", encoding="utf-8")

    print(header)
    print("\n".join(table))
    print(f"\n{len(rows)} requirements from {', '.join(s.name for s in specs)}; commit messages: {commit_note}")
    for line in notes:
        print("  note  " + line)
    for line in flags:
        print("  FLAG  " + line)
    print(f"matrix written to {STATE / 'matrix.md'} and {STATE / 'matrix.json'}")
    if flags:
        print(f"RESULT fail: {len(flags)} flag(s) not waived")
        return 1
    if commits is None and not args.no_commits:
        print("RESULT not verified: commit messages were not searched (no git repository)"
              + (f", so 'no-code' is undecided for {', '.join(undecided)}" if undecided else "")
              + ". Run again with --no-commits to accept a matrix built from files only")
        return 2
    print("RESULT pass")
    return 0


def cmd_waive(root, args):
    if args.flag not in WAIVABLE:
        print(f"blocked: only {' and '.join(WAIVABLE)} can be waived. An orphan-test or gone id is fixed by correcting the id")
        return 2
    reason = args.reason.strip()
    if len(reason) < 12 or PLACEHOLDER.search(reason):
        print("blocked: a waiver needs a real reason (a sentence saying why this requirement has no test or no code reference)")
        return 2
    specs = find_specs(root, args.spec)
    known = set()
    for spec in specs:
        if spec.is_file():
            known |= set(read_requirements(spec)[0])
    if args.id not in known:
        print(f"blocked: {args.id} is not defined in the spec")
        return 2
    waivers = load_waivers(root)
    if waivers is None:
        print(f"blocked: {STATE / 'waivers.json'} is not valid JSON")
        return 2
    waivers = [w for w in waivers if (w.get("id"), w.get("flag")) != (args.id, args.flag)]
    waivers.append({"id": args.id, "flag": args.flag, "reason": reason, "date": datetime.date.today().isoformat()})
    path = root / STATE / "waivers.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"waivers": waivers}, indent=2) + "\n", encoding="utf-8")
    print(f"waived {args.flag} for {args.id} in {STATE / 'waivers.json'}: {reason}")
    print("RESULT pass")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path.cwd(), help="project folder (default: current folder)")
    parser.add_argument("--spec", action="append", default=[], help="spec file; may be given more than once (default: found by name)")
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("matrix", help="build the matrix and the four flags")
    p.add_argument("--no-commits", action="store_true", help="do not search commit messages")
    p = sub.add_parser("waive", help="accept one flag for one id, with a reason")
    p.add_argument("id")
    p.add_argument("--flag", required=True, help="no-test or no-code")
    p.add_argument("--reason", required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    return {"matrix": cmd_matrix, "waive": cmd_waive}[args.action](root, args)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Take stock of a project's tests and list the source files no test seems to touch.

  scan   count test files, detect runners and CI config, find recently changed source files and
         source folders that no test file names or imports; print a table and write a gap table to fill
  check  check the filled gap table: every top risk has a named test that exists, or a stated reason for none

`scan` writes .mstack/test-gaps/inventory.json and a new .mstack/test-gaps/gaps.md (never overwriting
an older one). A test file "touches" a source file when its name matches (test_cart.py and cart.py,
cart.test.ts and cart.ts) or when one of its import lines or quoted paths names the source file.
That is a lead to read, not proof: a file can be imported and still not be tested, and code reached
only through another module shows as untouched.

Gap table columns: # | risk | file | changes | lines | action | test | reason
  action   add, update, keep, delete or no-test
  test     for add, update, keep, delete: a test file, optionally `path::test name`
  reason   for no-test and delete: why, in at least five words
  risk     what goes wrong for a user if this file is broken; needed in every row

Exit codes:
  scan   0 = pass: no untouched source file found, 2 = not verified: gaps are listed and wait for a decision
         (also 2 when there are no source files to look at)
  check  0 = pass, 1 = fail: a row is incomplete or a top risk was dropped,
         2 = not verified: a test named under `add` is not written yet, or the files are missing
"""
import argparse
import datetime
import json
import os
import pathlib
import re
import subprocess
import sys

STATE = pathlib.Path(".mstack") / "test-gaps"
SOURCE_EXT = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".rs", ".java", ".kt", ".swift", ".rb", ".php",
              ".cs", ".c", ".cc", ".cpp", ".scala", ".ex", ".exs", ".dart", ".vue", ".svelte"}
SKIP_DIRS = {".git", "node_modules", "dist", "build", "target", ".venv", "venv", "env", "__pycache__", ".mstack", "vendor",
             ".next", ".nuxt", "coverage", ".tox", "Pods", "DerivedData", ".testrun", ".idea", ".vscode", "out", ".gradle"}
TEST_DIRS = {"tests", "test", "__tests__", "spec", "specs", "e2e", "cypress", "testing", "integration_tests"}
TEST_NAME = re.compile(r"^(test_.+\.py|.+_test\.(py|go|rs|rb|exs|dart|c|cc|cpp)|.+\.(test|spec)\.[cm]?[jt]sx?|.+_spec\.rb|"
                       r".+Tests?\.(java|kt|swift|cs|php|scala)|.+\.cy\.[jt]sx?)$")
NOT_SOURCE = re.compile(r"(^|/)(__init__\.py|conftest\.py|setup\.py|manage\.py|.+\.d\.ts|.+\.config\.[cm]?[jt]s|.+\.min\.js|"
                        r"\.eslintrc\.[cm]?js|gulpfile\.js|Gruntfile\.js|build\.rs|Package\.swift)$")
IMPORT_LINE = re.compile(r"\b(import|require|from|use|include|load|mod|using)\b")
QUOTED = re.compile(r"""["'`]([^"'`\n]{1,200})["'`]""")
CI_FILES = (".gitlab-ci.yml", ".circleci/config.yml", "Jenkinsfile", "azure-pipelines.yml", "bitbucket-pipelines.yml",
            ".travis.yml", ".buildkite/pipeline.yml", ".drone.yml")
CI_TEST = re.compile(r"\b(pytest|unittest|jest|vitest|mocha|playwright|cypress|cargo test|go test|rspec|phpunit|mix test|"
                     r"swift test|xcodebuild test|flutter test|gradle\w* test|mvn\w* (test|verify)|(npm|pnpm|yarn|bun)( run)? test|make test|tox)\b")
ACTIONS = {"add", "update", "keep", "delete", "no-test"}
MAX_READ = 400_000


def git(root, *args):
    try:
        out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout if out.returncode == 0 else None


def list_files(root):
    listed = git(root, "ls-files", "--cached", "--others", "--exclude-standard")
    if listed is not None:
        names = [n for n in listed.splitlines() if n and (root / n).is_file()]
        via = "git"
    else:
        names, via = [], "folder walk (not a git repository)"
        for folder, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            names += [str((pathlib.Path(folder) / f).relative_to(root)) for f in files]
    return sorted(n for n in names if not (set(pathlib.PurePosixPath(n).parts[:-1]) & SKIP_DIRS)), via


def read(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read(MAX_READ)
    except OSError:
        return ""


def is_test(name):
    path = pathlib.PurePosixPath(name)
    return bool(TEST_NAME.match(path.name)) or bool(set(p.lower() for p in path.parts[:-1]) & TEST_DIRS)


def stems(name):
    """Names under which a test may refer to this source file, lower case."""
    path = pathlib.PurePosixPath(name)
    stem = path.name[: -len(path.suffix)] if path.suffix else path.name
    out = {stem.lower(), stem.split(".")[0].lower()}
    if stem.lower() in ("index", "mod", "main", "lib", "__init__") and len(path.parts) > 1:
        out = {path.parts[-2].lower()}
    return {s for s in out if s}


def test_subject(name):
    """The source stem a test file is named after: test_cart.py -> cart, Cart.test.tsx -> cart, CartTests.swift -> cart."""
    stem = pathlib.PurePosixPath(name).name
    stem = re.sub(r"\.(test|spec|cy)\.[cm]?[jt]sx?$|\.[A-Za-z0-9]+$", "", stem)
    stem = re.sub(r"^test_|_test$|_spec$|Tests?$", "", stem)
    return stem.lower()


def mentions(text):
    found = set()
    for line in text.splitlines():
        if IMPORT_LINE.search(line):
            found.update(t.lower() for t in re.findall(r"[A-Za-z0-9_-]+", line))
        for quoted in QUOTED.findall(line):
            if "/" in quoted or "." in quoted:
                found.update(t.lower() for t in re.findall(r"[A-Za-z0-9_-]+", quoted))
    return found


def detect_runners(root, files, tests):
    found = []
    names = set(files)
    package = root / "package.json"
    if package.exists():
        try:
            data = json.loads(read(package))
        except ValueError:
            data = {}
        deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        for dep, label in (("jest", "jest"), ("vitest", "vitest"), ("mocha", "mocha"), ("ava", "ava"), ("@playwright/test", "playwright"),
                           ("cypress", "cypress"), ("jasmine", "jasmine"), ("karma", "karma")):
            if dep in deps:
                found.append((label, "package.json dependency"))
        script = data.get("scripts", {}).get("test", "")
        if script and "no test specified" not in script:
            found.append(("npm test script", script[:60]))
    pytest_text = read(root / "pyproject.toml") + read(root / "setup.cfg") + read(root / "tox.ini")
    if "pytest.ini" in names or "pytest" in pytest_text:
        found.append(("pytest", "pytest.ini or project config"))
    elif any(n.endswith(".py") for n in tests):
        found.append(("python unittest or pytest", "by test file names only; no config found"))
    for marker, label in (("Cargo.toml", "cargo test"), ("go.mod", "go test"), ("mix.exs", "mix test"), ("Package.swift", "swift test"),
                          ("pubspec.yaml", "dart or flutter test")):
        if marker in names:
            found.append((label, marker))
    for marker, word, label in (("Gemfile", "rspec", "rspec"), ("Gemfile", "minitest", "minitest"), ("pom.xml", "junit", "junit (maven)"),
                                ("build.gradle", "junit", "junit (gradle)"), ("build.gradle.kts", "junit", "junit (gradle)"),
                                ("composer.json", "phpunit", "phpunit")):
        if marker in names and word in read(root / marker).lower():
            found.append((label, marker))
    if any(line.startswith("test:") for line in read(root / "Makefile").splitlines()):
        found.append(("make test", "Makefile target"))
    return found


def detect_ci(root, files):
    configs = [n for n in files if n.startswith(".github/workflows/") and n.endswith((".yml", ".yaml"))]
    configs += [n for n in CI_FILES if n in set(files)]
    runs_tests = []
    for name in configs:
        for number, line in enumerate(read(root / name).splitlines(), 1):
            if CI_TEST.search(line):
                runs_tests.append(f"{name}:{number}: {line.strip()[:80]}")
                break
    return configs, runs_tests


def cmd_scan(root, args):
    files, via = list_files(root)
    tests = [n for n in files if pathlib.PurePosixPath(n).suffix in SOURCE_EXT and is_test(n)]
    sources = [n for n in files if pathlib.PurePosixPath(n).suffix in SOURCE_EXT and not is_test(n) and not NOT_SOURCE.search(n)]
    if not sources:
        print(f"files listed by {via}: {len(files)}; none is a source file this script knows")
        print("RESULT not verified: no source files found here. Run it in the project folder, or pass --root")
        return 2

    subjects, mentioned = set(), set()
    for name in tests:
        subjects.add(test_subject(name))
        mentioned |= mentions(read(root / name))
    inline = {n for n in sources if n.endswith(".rs") and re.search(r"#\[(cfg\(test\)|test)\]", read(root / n))}
    go_dirs = {str(pathlib.PurePosixPath(n).parent) for n in tests if n.endswith("_test.go")}

    def touched(name):
        if name in inline or (name.endswith(".go") and str(pathlib.PurePosixPath(name).parent) in go_dirs):
            return True
        return bool(stems(name) & subjects) or bool(stems(name) & mentioned)

    since = f"{args.since_days} days ago"
    log = git(root, "log", f"--since={since}", "--name-only", "--pretty=format:")
    changes = {}
    for line in (log or "").splitlines():
        if line.strip():
            changes[line.strip()] = changes.get(line.strip(), 0) + 1
    for line in (git(root, "status", "--porcelain=v1", "-uall") or "").splitlines():
        name = line[3:].split(" -> ")[-1].strip('"')
        changes[name] = changes.get(name, 0) + 1

    rows = []
    for name in sources:
        rows.append({"file": name, "lines": len(read(root / name).splitlines()), "changes": changes.get(name, 0), "touched": touched(name)})
    untouched = [r for r in rows if not r["touched"]]
    recent_untouched = sorted([r for r in untouched if r["changes"]], key=lambda r: (-r["changes"], -r["lines"], r["file"]))
    quiet_untouched = sorted([r for r in untouched if not r["changes"]], key=lambda r: (-r["lines"], r["file"]))
    top = (recent_untouched + quiet_untouched)[: args.top]

    folders = {}
    for r in rows:
        folder = str(pathlib.PurePosixPath(r["file"]).parent)
        stat = folders.setdefault(folder, {"sources": 0, "touched": 0, "lines": 0})
        stat["sources"] += 1
        stat["touched"] += r["touched"]
        stat["lines"] += r["lines"]
    bare_folders = sorted(((f, s) for f, s in folders.items() if s["touched"] == 0), key=lambda item: -item[1]["lines"])

    runners = detect_runners(root, files, tests)
    ci_configs, ci_tests = detect_ci(root, files)

    print(f"project: {root}   files listed by {via}")
    print(f"source files: {len(sources)}   test files: {len(tests)}   source files with a test that names or imports them: {len(rows) - len(untouched)}")
    print("\nrunners detected:")
    for label, why in runners:
        print(f"  {label:28} {why}")
    if not runners:
        print("  none" + ("  (there are test files, but nothing that says how to run them)" if tests else ""))
    if runners and not tests:
        print("  note: a runner is configured but no test file was found")
    print("\nCI config:")
    for name in ci_configs:
        print(f"  {name}")
    if not ci_configs:
        print("  none found: nothing runs the tests automatically")
    elif not ci_tests:
        print("  note: no line in the CI config looks like a test command")
    for line in ci_tests:
        print(f"  runs tests: {line}")

    if log is None:
        print(f"\nrecent changes: not verified (no git history here); files are ranked by size only")
    print(f"\nsource files changed in the last {args.since_days} days that no test names or imports: {len(recent_untouched)}")
    print(f"  {'changes':>7} {'lines':>6}  file")
    for r in recent_untouched[:30]:
        print(f"  {r['changes']:>7} {r['lines']:>6}  {r['file']}")
    if len(recent_untouched) > 30:
        print(f"  ... {len(recent_untouched) - 30} more in inventory.json")
    print(f"\nsource folders where no file is named or imported by a test: {len(bare_folders)}")
    print(f"  {'files':>7} {'lines':>6}  folder")
    for folder, stat in bare_folders[:20]:
        print(f"  {stat['sources']:>7} {stat['lines']:>6}  {folder}/")

    out = root / STATE
    out.mkdir(parents=True, exist_ok=True)
    commit = (git(root, "rev-parse", "--short", "HEAD") or "").strip() or None
    inventory = {"generated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "commit": commit,
                 "since_days": args.since_days, "listed_by": via, "sources": len(sources), "tests": tests,
                 "runners": [list(r) for r in runners], "ci_configs": ci_configs, "ci_runs_tests": ci_tests,
                 "untouched": untouched, "bare_folders": [{"folder": f, **s} for f, s in bare_folders],
                 "top": [r["file"] for r in top], "history_available": log is not None}
    (out / "inventory.json").write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    gaps, n = out / "gaps.md", 1
    while gaps.exists():
        n += 1
        gaps = out / f"gaps-{n}.md"
    lines = ["# Test gaps", "",
             f"Generated {inventory['generated']} by inventory.py" + (f" at commit {commit}" if commit else "") + ".",
             "Fill risk, action, test and reason in every row. Actions: add, update, keep, delete, no-test.",
             "Add rows for risks the inventory cannot see. Do not remove rows.", "",
             f"| # | risk | file | changes | lines | action | test | reason |", "|---|---|---|---|---|---|---|---|"]
    lines += [f"| {i} |  | {r['file']} | {r['changes']} | {r['lines']} |  |  |  |" for i, r in enumerate(top, 1)]
    gaps.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nwrote {out / 'inventory.json'}")
    print(f"wrote {gaps} with {len(top)} row(s): the {args.top} largest risks by recent change, then by size")
    print("a file counts as touched when a test file is named after it or names it on an import line or in a quoted path; read the leads, they are not proof")
    if not untouched:
        print("RESULT pass: every source file is named or imported by some test file; nothing to decide")
        return 0
    flag = "" if gaps.name == "gaps.md" else f" --gaps {STATE / gaps.name}"
    print(f"RESULT not verified: {len(top)} top risk(s) wait for a decision in {gaps.name}; fill it, then run: inventory.py check{flag}")
    return 2


def table_rows(text):
    header, rows = None, []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c) and any(cells):
            continue
        if header is None:
            header = [c.lower() for c in cells]
            continue
        cells += [""] * (len(header) - len(cells))
        rows.append((number, dict(zip(header, cells))))
    return header, rows


def cmd_check(root, args):
    folder = root / STATE
    gaps = args.gaps if args.gaps else folder / "gaps.md"
    gaps = gaps if gaps.is_absolute() else root / gaps
    if not gaps.is_file():
        print(f"RESULT not verified: {gaps} not found; run: inventory.py scan")
        return 2
    try:
        inventory = json.loads((folder / "inventory.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print(f"RESULT not verified: {folder / 'inventory.json'} is missing or unreadable; run: inventory.py scan")
        return 2
    header, rows = table_rows(gaps.read_text(encoding="utf-8"))
    needed = {"risk", "file", "action", "test", "reason"}
    if header is None or not needed <= set(header):
        print(f"RESULT not verified: {gaps} has no table with the columns {', '.join(sorted(needed))}")
        return 2
    problems, pending, counts = [], [], {}
    listed = set()
    for number, row in rows:
        label = f"row {row.get('#') or '?'} (line {number}, {row['file'] or 'no file'})"
        listed.add(row["file"])
        action = row["action"].lower().strip("` ")
        counts[action] = counts.get(action, 0) + 1
        if not row["risk"]:
            problems.append(f"{label}: no risk: say what goes wrong for a user if this breaks")
        if action not in ACTIONS:
            problems.append(f"{label}: action is '{row['action']}', expected one of {', '.join(sorted(ACTIONS))}")
            continue
        words = len(row["reason"].split())
        if action in ("no-test", "delete") and words < 5:
            problems.append(f"{label}: '{action}' needs a reason of at least five words (found {words})")
        if action == "no-test":
            continue
        target = row["test"].strip("` ")
        if not target:
            problems.append(f"{label}: '{action}' needs a named test (a test file, or file::test name)")
            continue
        path_text, _, test_name = target.partition("::")
        path = root / path_text.strip()
        if not path.is_file():
            if action == "add":
                pending.append(f"{label}: {path_text} is named but not written yet")
            else:
                problems.append(f"{label}: test file not found: {path_text}")
        elif test_name.strip() and test_name.strip() not in read(path):
            if action == "add":
                pending.append(f"{label}: {path_text} exists but has no test called '{test_name.strip()}' yet")
            else:
                problems.append(f"{label}: '{test_name.strip()}' is not in {path_text}")
    for name in inventory.get("top", []):
        if name not in listed:
            problems.append(f"top risk {name} from the inventory has no row: it was removed, not decided")
    print(f"gap table: {gaps}   rows: {len(rows)}   " + "  ".join(f"{k or '(empty)'} {v}" for k, v in sorted(counts.items())))
    for line in problems:
        print(f"  problem: {line}")
    for line in pending:
        print(f"  pending: {line}")
    if problems:
        print(f"RESULT fail: {len(problems)} row problem(s) above")
        return 1
    if pending:
        print(f"RESULT not verified: {len(pending)} test(s) are decided but not written yet")
        return 2
    if not rows:
        print("RESULT pass: the inventory found no gap and no row was added")
        return 0
    print("RESULT pass")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path.cwd(), help="project folder (default: current folder)")
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("scan", help="take the inventory and write the gap table")
    p.add_argument("--since-days", type=int, default=90, help="how far back 'recently changed' looks (default 90)")
    p.add_argument("--top", type=int, default=10, help="how many risks go into the gap table (default 10)")
    p = sub.add_parser("check", help="check the filled gap table")
    p.add_argument("--gaps", type=pathlib.Path, help="the gap table (default: .mstack/test-gaps/gaps.md)")
    args = parser.parse_args()
    root = args.root.resolve()
    return {"scan": cmd_scan, "check": cmd_check}[args.action](root, args)


if __name__ == "__main__":
    sys.exit(main())

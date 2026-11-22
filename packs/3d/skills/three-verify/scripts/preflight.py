#!/usr/bin/env python3
"""Check a project's three.js code against the three.js version that is really installed.

  preflight.py [project folder]

What it does:
  1. Reads the installed version from node_modules/three/package.json (also looks in parent folders, for
     workspaces). If three is only declared in package.json and not installed, it says so and can confirm nothing.
  2. Checks every import of three/addons/... or three/examples/jsm/... against the files of the installed package.
     A path that is not there is a confirmed failure, with no list involved.
  3. Scans the source for names and paths in references/api_changes.json that were removed, renamed or added
     at some revision. That list is short, dated and unverified, so a hit counts as confirmed only when the
     installed package agrees (the name is absent from its build files, or the folder is absent).

Exit codes: 0 = pass, nothing flagged
            1 = fail, at least one confirmed mismatch between the code and the installed three.js
            2 = not verified (hits the installed package could not confirm, or three is not installed)
                or blocked (no three.js in this project at all)
This script only reads files. It runs nothing from the project.
"""
import argparse
import json
import pathlib
import re
import sys

CHANGES = pathlib.Path(__file__).resolve().parent.parent / "references" / "api_changes.json"
SKIP_DIRS = {"node_modules", ".git", "dist", "build", "out", ".next", ".nuxt", ".svelte-kit", "coverage", ".mstack", ".testrun", "vendor"}
SOURCE = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte", ".astro", ".html"}
IMPORT = re.compile(r"""['"]three/(addons|examples/jsm)/([^'"]+)['"]""")
MAX_BYTES = 1_000_000
MAX_FILES = 5000


def find_installed(project):
    """Return (package folder, version) for the nearest node_modules/three, or (None, None)."""
    folder = project.resolve()
    for _ in range(4):
        package = folder / "node_modules" / "three" / "package.json"
        if package.is_file():
            try:
                return package.parent, json.loads(package.read_text(encoding="utf-8")).get("version")
            except ValueError:
                return package.parent, None
        if folder.parent == folder:
            break
        folder = folder.parent
    return None, None


def declared_version(project):
    package = project / "package.json"
    if not package.is_file():
        return None, {}
    try:
        data = json.loads(package.read_text(encoding="utf-8"))
    except ValueError:
        return None, {}
    deps = {**data.get("devDependencies", {}), **data.get("peerDependencies", {}), **data.get("dependencies", {})}
    return deps.get("three"), deps


def revision(version):
    """three.js versions look like 0.160.1; the middle number is the revision."""
    match = re.search(r"(\d+)\.(\d+)", version or "")
    if not match:
        return None
    return int(match.group(2)) if match.group(1) == "0" else None


def sources(project):
    count = 0
    stack = [project]
    while stack:
        folder = stack.pop()
        try:
            entries = sorted(folder.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name not in SKIP_DIRS and not entry.name.startswith("."):
                    stack.append(entry)
            elif entry.suffix in SOURCE and entry.stat().st_size <= MAX_BYTES:
                count += 1
                if count > MAX_FILES:
                    return
                yield entry


def build_text(package):
    text = []
    for path in sorted((package / "build").glob("*.js")) if (package / "build").is_dir() else []:
        if ".min." not in path.name and path.stat().st_size < 8_000_000:
            text.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(text)


def addon_exists(package, rest):
    base = package / "examples" / "jsm" / rest
    return any(p.is_file() for p in (base, base.with_name(base.name + ".js"), base / "index.js"))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", nargs="?", default=".", type=pathlib.Path, help="project folder (default: current folder)")
    parser.add_argument("--changes", type=pathlib.Path, default=CHANGES, help="the dated list of API changes")
    parser.add_argument("--json", action="store_true", help="print one JSON object")
    args = parser.parse_args()
    project = args.project
    if not project.is_dir():
        print(f"blocked: {project} is not a folder")
        return 2
    try:
        listed = json.loads(args.changes.read_text(encoding="utf-8"))
        changes = listed["changes"]
    except (OSError, ValueError, KeyError) as exc:
        print(f"RESULT not verified: the change list {args.changes} cannot be read: {exc}")
        return 2

    package, installed = find_installed(project)
    declared, deps = declared_version(project)
    if package is None and declared is None:
        print("blocked: no three.js here: neither node_modules/three nor a 'three' entry in package.json. Point this at the project folder.")
        return 2
    version = installed or declared
    rev = revision(version)
    print(f"three.js: {installed + ' installed at ' + str(package) if installed else 'NOT installed; package.json declares ' + str(declared)}"
          + (f" (revision r{rev})" if rev is not None else " (revision not readable)"))
    for name in ("@react-three/fiber", "@react-three/drei", "@react-three/xr"):
        if name in deps:
            print(f"{name}: declared {deps[name]}")
    build = build_text(package) if package else ""
    exports = {}
    if package:
        try:
            exports = json.loads((package / "package.json").read_text(encoding="utf-8")).get("exports", {}) or {}
        except ValueError:
            exports = {}

    confirmed, unconfirmed, notes, scanned = [], [], [], 0
    compiled = [(entry, re.compile(entry["pattern"])) for entry in changes]
    for path in sources(project):
        scanned += 1
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        shown = path.relative_to(project)
        for number, line in enumerate(lines, 1):
            for match in IMPORT.finditer(line):
                if package and not addon_exists(package, match.group(2)):
                    confirmed.append(f"{shown}:{number}: import 'three/{match.group(1)}/{match.group(2)}' is not in the installed package | {line.strip()[:120]}")
            for entry, pattern in compiled:
                if not pattern.search(line):
                    continue
                applies = rev is not None and (rev < entry["since"] if entry["kind"] == "added" else rev >= entry["since"])
                if rev is not None and not applies:
                    continue
                what = (f"{entry['id']}: listed as {entry['kind']} in r{entry['since']}; use {entry['use']}")
                where = f"{shown}:{number}: {what} | {line.strip()[:120]}"
                if not package:
                    unconfirmed.append(where)
                elif "confirm_symbol_absent" in entry and build:
                    present = re.search(r"\b" + re.escape(entry["confirm_symbol_absent"]) + r"\b", build)
                    if present and entry["kind"] != "added":
                        notes.append(where + " | still present in the installed build, so probably deprecated, not broken")
                    elif present:
                        continue
                    else:
                        confirmed.append(where + f" | confirmed: '{entry['confirm_symbol_absent']}' does not occur in the installed build")
                elif "confirm_path_absent" in entry:
                    if (package / entry["confirm_path_absent"]).exists():
                        continue
                    confirmed.append(where + f" | confirmed: the installed package has no {entry['confirm_path_absent']}/")
                elif "confirm_export_absent" in entry and isinstance(exports, dict) and exports:
                    if entry["confirm_export_absent"] in exports:
                        continue
                    confirmed.append(where + f" | confirmed: the installed package exports no '{entry['confirm_export_absent']}'")
                else:
                    unconfirmed.append(where)

    if args.json:
        print(json.dumps({"installed": installed, "declared": declared, "revision": rev, "files_scanned": scanned,
                          "confirmed": confirmed, "unconfirmed": unconfirmed, "notes": notes}, indent=2))
    else:
        print(f"scanned {scanned} source files against {len(changes)} listed changes (list checked {listed.get('checked', '?')}, all entries unverified)")
        for line in confirmed:
            print(f"FAIL {line}")
        for line in unconfirmed:
            print(f"unconfirmed {line}")
        for line in notes:
            print(f"note {line}")
    if confirmed:
        print(f"RESULT fail: {len(confirmed)} lines do not match the installed three.js")
        return 1
    if not installed:
        print("RESULT not verified: three is declared but not installed, so nothing could be confirmed against the real package"
              + (f"; {len(unconfirmed)} lines match the unverified list" if unconfirmed else ""))
        return 2
    if scanned == 0:
        print("RESULT not verified: no source files found to scan")
        return 2
    if unconfirmed:
        print(f"RESULT not verified: {len(unconfirmed)} lines match the unverified list and the installed package could not confirm them")
        return 2
    print("RESULT pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())

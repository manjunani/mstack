#!/usr/bin/env python3
"""Keep the record of one dependency upgrade, and refuse to call it done until four things are on it.

  upgrade.py start PACKAGE --to VERSION [--root DIR]
      Reads the version in use now from the lock file (or, failing that, the manifest) and records it with
      the target. Understood: package-lock.json, pnpm-lock.yaml, yarn.lock, package.json, poetry.lock,
      uv.lock, requirements*.txt, pyproject.toml, Cargo.lock, Cargo.toml, go.mod, Gemfile.lock.

  upgrade.py changelog PACKAGE --file FILE
      Records the changelog or release notes the user supplied (a saved file) and lists which version
      sections between the old and the new version it holds. The target's own section must be there.

  upgrade.py test PACKAGE --phase before|after -- COMMAND [ARG ...]
      Runs the test command (without a shell) and records its exit code and last lines.
      "before" runs on the old version, "after" on the new one, with the same command.

  upgrade.py check PACKAGE
      Reads the version in use again and checks the record:
        1. the old version was recorded       2. the lock or manifest now holds the target
        3. the target's changelog section was supplied
        4. the same test command passed before and passes after
      Anything missing ends as not verified, never as done.

  upgrade.py show PACKAGE       print the record

The record is .mstack/dep-upgrade/<package>.json. This script installs nothing and edits no project file:
the upgrade itself is made with the project's own package manager, after the user said yes.

Exit codes: 0 = pass, 1 = fail (tests fail after the upgrade, or the version did not change),
            2 = not verified or blocked (a piece of the record is missing, or bad input).
"""
import argparse
import datetime
import json
import pathlib
import re
import subprocess
import sys

STATE = pathlib.Path(".mstack") / "dep-upgrade"
LOCKS = ["package-lock.json", "pnpm-lock.yaml", "yarn.lock", "poetry.lock", "uv.lock", "Cargo.lock", "go.mod", "Gemfile.lock"]
MANIFESTS = ["package.json", "pyproject.toml", "Cargo.toml"]
VERSION = re.compile(r"v?(\d+(?:\.\d+)*(?:[-.+]?[0-9A-Za-z.]+)?)")


def norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def versions_in(path, package):
    """Return the versions of PACKAGE named in one file (a list, possibly empty)."""
    text = path.read_text(encoding="utf-8", errors="replace")
    name, esc = path.name, re.escape(package)
    found = []
    if name == "package-lock.json":
        try:
            data = json.loads(text)
        except ValueError:
            return []
        for key, info in (data.get("packages") or {}).items():
            if key.endswith("node_modules/" + package) and isinstance(info, dict) and info.get("version"):
                found.append(info["version"])
        if not found and isinstance(data.get("dependencies"), dict) and package in data["dependencies"]:
            found.append(data["dependencies"][package].get("version"))
    elif name == "package.json":
        try:
            data = json.loads(text)
        except ValueError:
            return []
        for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
            spec = (data.get(section) or {}).get(package)
            if spec:
                found.append(spec)
    elif name == "pnpm-lock.yaml":
        found += re.findall(r"^\s+['\"]?/?" + esc + r"@(\d[^:('\"\s]*)", text, re.M)
    elif name == "yarn.lock":
        for block in re.split(r"\n\s*\n", text):
            head = block.strip().splitlines()[0] if block.strip() else ""
            if re.search(r"(^|[\s,\"])" + esc + r"@", head):
                m = re.search(r"^\s+version:?\s+\"?([^\"\s]+)", block, re.M)
                if m:
                    found.append(m.group(1))
    elif name in ("poetry.lock", "uv.lock", "Cargo.lock"):
        for block in text.split("[[package]]"):
            m = re.search(r'^name\s*=\s*"([^"]+)"\s*$', block, re.M)
            v = re.search(r'^version\s*=\s*"([^"]+)"', block, re.M)
            if m and v and norm(m.group(1)) == norm(package):
                found.append(v.group(1))
    elif name == "go.mod":
        found += re.findall(r"^\s*(?:require\s+)?" + esc + r"\s+(v[^\s/]+)", text, re.M)
    elif name == "Gemfile.lock":
        found += re.findall(r"^    " + esc + r" \(([^)]+)\)", text, re.M)
    elif name == "Cargo.toml":
        found += re.findall(r"^\s*" + esc + r"\s*=\s*(?:\"([^\"]+)\"|\{[^}]*version\s*=\s*\"([^\"]+)\")", text, re.M)
        found = [a or b for a, b in found] if found and isinstance(found[0], tuple) else found
    elif name == "pyproject.toml" or name.startswith("requirements"):
        for m in re.finditer(r"(?im)^[\s\"']*([A-Za-z0-9_.-]+)\s*(?:\[[^\]]*\])?\s*(==|>=|~=|===)\s*([^\s,;\"'#]+)", text):
            if norm(m.group(1)) == norm(package):
                found.append(("" if m.group(2) in ("==", "===") else m.group(2)) + m.group(3))
        for m in re.finditer(r"(?m)^\s*([A-Za-z0-9_.-]+)\s*=\s*[\"']([^\"']+)[\"']", text):
            if norm(m.group(1)) == norm(package) and name == "pyproject.toml":
                found.append(m.group(2))
    return [v for v in dict.fromkeys(found) if v]


def current(root, package):
    """Return (versions, file name, kind) from the first lock file that names the package, else a manifest."""
    candidates = [(root / n, "lock") for n in LOCKS] + sorted((p, "pinned") for p in root.glob("requirements*.txt")) + [(root / n, "manifest") for n in MANIFESTS]
    for path, kind in candidates:
        if path.is_file():
            found = versions_in(path, package)
            if found:
                return found, path.name, kind
    return [], None, None


def as_tuple(version):
    m = VERSION.search(version or "")
    return tuple(int(p) for p in re.findall(r"\d+", m.group(1).split("-")[0].split("+")[0])[:4]) if m else ()


def load(root, package):
    path = root / STATE / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', package)}.json"
    return path, (json.loads(path.read_text(encoding="utf-8")) if path.exists() else None)


def save(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    ignore = path.parent.parent / ".gitignore"
    have = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
    if "dep-upgrade/" not in have.split():
        ignore.write_text(have + ("\n" if have and not have.endswith("\n") else "") + "dep-upgrade/\n", encoding="utf-8")
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def cmd_start(args, root):
    path, record = load(root, args.package)
    if record and not args.restart:
        print(f"blocked: a record for {args.package} exists ({record['from']} to {record['to']}). Continue it, or pass --restart.")
        return 2
    found, source, kind = current(root, args.package)
    if not found:
        print(f"blocked: {args.package} is not named in any lock or manifest file under {root}")
        return 2
    if args.to in found or args.to.lstrip("v") in [f.lstrip("v") for f in found]:
        print(f"blocked: {source} already holds {args.to}; there is nothing to upgrade")
        return 2
    record = {"package": args.package, "from": found[0], "from_all": found, "from_source": source, "from_kind": kind,
              "to": args.to, "started": now(), "changelog": None, "tests": {}}
    save(path, record)
    major = as_tuple(found[0])[:1] != as_tuple(args.to)[:1]
    print(f"{args.package}: {found[0]} in {source} ({kind})" + (f"; other versions in the same file: {', '.join(found[1:])}" if len(found) > 1 else ""))
    print(f"target: {args.to}" + ("  (a new MAJOR version: read its breaking changes before anything else)" if major else ""))
    if kind != "lock":
        print(f"  note: {source} is not a lock file, so this is the declared version, not necessarily the one installed")
    print(f"record: {path}")
    print("next: changelog, then test --phase before, then upgrade with the package manager, then test --phase after, then check")
    print("RESULT pass: upgrade started")
    return 0


def cmd_changelog(args, root):
    path, record = load(root, args.package)
    if not record:
        print(f"blocked: no record for {args.package}; run start first")
        return 2
    if not args.file.is_file() or args.file.stat().st_size == 0:
        print(f"blocked: no changelog text at {args.file}")
        return 2
    text = args.file.read_text(encoding="utf-8", errors="replace")
    low, high = as_tuple(record["from"]), as_tuple(record["to"])
    sections = []
    for line in text.splitlines():
        if re.match(r"^\s*(#{1,4}\s|\[?v?\d+\.\d+|=+|release|version)", line, re.I):
            for m in VERSION.finditer(line):
                if "." in m.group(1):
                    sections.append(m.group(1))
                    break
    seen = list(dict.fromkeys(sections))
    between = [v for v in seen if low < as_tuple(v) <= high]
    target_found = any(as_tuple(v) == high for v in seen)
    record["changelog"] = {"file": str(args.file), "sections_between": between, "target_section": target_found, "when": now()}
    save(path, record)
    print(f"changelog: {args.file}; {len(seen)} version headings; between {record['from']} and {record['to']}: {', '.join(between) or 'none'}")
    if not target_found:
        print(f"RESULT not verified: no section for {record['to']} in this file; the changes in the target version are unread")
        return 2
    print(f"RESULT pass: changelog recorded with {len(between)} section(s) to read")
    return 0


def cmd_test(args, root):
    path, record = load(root, args.package)
    if not record:
        print(f"blocked: no record for {args.package}; run start first")
        return 2
    if not args.command:
        print("blocked: give the test command after --")
        return 2
    other = record["tests"].get("before" if args.phase == "after" else "after")
    if other and other["command"] != args.command:
        print(f"blocked: the {args.phase} run must use the same command as the other run: {' '.join(other['command'])}")
        return 2
    found, source, _ = current(root, args.package)
    print(f"{args.package} in {source}: {', '.join(found) or 'not found'}")
    if args.phase == "before" and record["to"] in found:
        print("blocked: the target version is already in place; the 'before' run must use the old version")
        return 2
    print(f"running ({args.phase}): {' '.join(args.command)}", flush=True)
    try:
        done = subprocess.run(args.command, cwd=root, capture_output=True, text=True, timeout=args.timeout)
        code, tail = done.returncode, (done.stdout + done.stderr).strip().splitlines()[-15:]
    except FileNotFoundError:
        print(f"blocked: command not found: {args.command[0]}")
        return 2
    except subprocess.TimeoutExpired:
        code, tail = None, [f"timed out after {args.timeout} seconds"]
    record["tests"][args.phase] = {"command": args.command, "exit": code, "tail": tail, "versions": found, "when": now()}
    save(path, record)
    for line in tail[-6:]:
        print("  | " + line)
    if code == 0:
        print(f"RESULT pass: tests pass ({args.phase})")
        return 0
    print(f"RESULT fail: tests exit {code} ({args.phase})")
    return 1


def cmd_check(args, root):
    path, record = load(root, args.package)
    if not record:
        print(f"blocked: no record for {args.package}; run start first")
        return 2
    found, source, _ = current(root, args.package)
    before, after, log = record["tests"].get("before"), record["tests"].get("after"), record.get("changelog")
    items = [
        ("old version recorded", True, f"{record['from']} from {record['from_source']}"),
        ("target in place", record["to"] in found or record["to"].lstrip("v") in [f.lstrip("v") for f in found],
         f"{source} holds {', '.join(found) or 'nothing'}; target {record['to']}"),
        ("changelog read", bool(log and log["target_section"]), f"{log['file']}, sections {', '.join(log['sections_between'])}" if log else "not supplied"),
        ("tests before", bool(before and before["exit"] == 0 and record["from"] in before["versions"]),
         (f"exit {before['exit']} on {', '.join(before['versions'])}" if before else "not run")),
        ("tests after", bool(after and after["exit"] == 0 and found and after["versions"] == found),
         (f"exit {after['exit']} on {', '.join(after['versions'])}" + ("" if after["versions"] == found else "; STALE: the versions changed since this run, run it again") if after else "not run")),
    ]
    for label, ok, detail in items:
        print(f"  {'ok  ' if ok else 'MISS'} {label}: {detail}")
    if before and after and before["command"] != after["command"]:
        print("RESULT not verified: the before and after runs used different commands")
        return 2
    if after and after["exit"] not in (0, None) and before and before["exit"] == 0:
        print(f"RESULT fail: the tests passed on {record['from']} and fail on {record['to']}. Revert the upgrade or fix the breakage; do not call it done.")
        return 1
    if after and found and not items[1][1] and record["from"] in found:
        print(f"RESULT fail: {source} still holds {record['from']}; the upgrade did not happen, so the after run tested the old version")
        return 1
    missing = [label for label, ok, _ in items if not ok]
    if before and before["exit"] != 0:
        print(f"RESULT not verified: the tests already failed on the old version, so they cannot judge the upgrade")
        return 2
    if missing:
        print("RESULT not verified: missing " + ", ".join(missing))
        return 2
    record["done"] = now()
    save(path, record)
    print(f"RESULT pass: {args.package} {record['from']} to {record['to']}; changelog read; same tests pass before and after")
    return 0


def cmd_show(args, root):
    path, record = load(root, args.package)
    if not record:
        print(f"blocked: no record for {args.package}")
        return 2
    print(json.dumps(record, indent=2))
    return 0


def split_command(argv):
    """Everything after the first "--" is the command, kept exactly as given."""
    if "--" in argv:
        cut = argv.index("--")
        return argv[:cut], argv[cut + 1:]
    return argv, []


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path.cwd(), help="project folder (default: current folder)")
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("start", help="record the version in use and the target")
    p.add_argument("package")
    p.add_argument("--to", required=True, help="target version")
    p.add_argument("--restart", action="store_true", help="replace an existing record")
    p = sub.add_parser("changelog", help="record the changelog the user supplied")
    p.add_argument("package")
    p.add_argument("--file", required=True, type=pathlib.Path)
    p = sub.add_parser("test", help="run the test command before or after the upgrade")
    p.add_argument("package")
    p.add_argument("--phase", required=True, choices=["before", "after"])
    p.add_argument("--timeout", type=int, default=1800)
    p = sub.add_parser("check", help="decide whether the upgrade is done")
    p.add_argument("package")
    p = sub.add_parser("show", help="print the record")
    p.add_argument("package")
    argv, command = split_command(sys.argv[1:])
    args = parser.parse_args(argv)
    args.command = command
    root = args.root.resolve()
    if not root.is_dir():
        print(f"blocked: {root} is not a folder")
        return 2
    return {"start": cmd_start, "changelog": cmd_changelog, "test": cmd_test, "check": cmd_check, "show": cmd_show}[args.action](args, root)


if __name__ == "__main__":
    sys.exit(main())

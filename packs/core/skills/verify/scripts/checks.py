#!/usr/bin/env python3
"""Run a project's own checks and keep a record of each result, tied to the exact code state.

  detect   propose checks from the project's files (package.json, pyproject.toml, Cargo.toml, go.mod, Makefile)
  run      run the checks in .mstack/checks.json and write an evidence record for each
  status   show the latest record for each check and whether it still matches the code

Exit codes: 0 = every check passed on the current code state
            1 = at least one check failed
            2 = not verified: no checks defined, a tool is missing, or a record is stale or absent
This script never edits project code. It writes only under .mstack/.
"""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import sys


def _find_git():
    """The git program: MSTACK_GIT when set, otherwise the first git that runs. On macOS /usr/bin/git is
    an xcrun shim that fails inside a sandbox (it cannot write its cache), so the real binaries come next."""
    if os.environ.get("MSTACK_GIT"):
        return os.environ["MSTACK_GIT"]
    for candidate in ("git", "/Applications/Xcode.app/Contents/Developer/usr/bin/git",
                      "/Library/Developer/CommandLineTools/usr/bin/git", "/opt/homebrew/bin/git", "/usr/local/bin/git"):
        try:
            if subprocess.run([candidate, "--version"], capture_output=True, timeout=10).returncode == 0:
                return candidate
        except (OSError, subprocess.SubprocessError):
            continue
    return "git"


GIT = _find_git()

STATE = ".mstack"
TAIL_LINES = 20


def git(root, *args):
    try:
        out = subprocess.run([GIT, "-C", str(root), *args], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout if out.returncode == 0 else None


def code_state(root):
    """Return (commit, tree fingerprint, dirty). The fingerprint changes when any tracked or untracked file changes."""
    head = git(root, "rev-parse", "HEAD")
    if head is None:
        return None, None, None
    scope = ["--", ".", f":(exclude){STATE}"]
    status = git(root, "status", "--porcelain=v1", "-uall", *scope) or ""
    diff = git(root, "diff", "HEAD", *scope) or ""
    digest = hashlib.sha256((head + status + diff).encode("utf-8", "replace"))
    for line in status.splitlines():
        if line.startswith("?? "):
            path = root / line[3:].strip().strip('"')
            try:
                stat = path.stat()
                digest.update(f"{line[3:]}:{stat.st_size}:{stat.st_mtime_ns}".encode())
            except OSError:
                pass
    return head.strip(), digest.hexdigest()[:16], bool(status.strip())


def detect(root):
    found = []

    def add(name, command, proves):
        if name not in {c["name"] for c in found}:
            found.append({"name": name, "command": command, "proves": proves})

    package = root / "package.json"
    if package.exists():
        try:
            scripts = json.loads(package.read_text(encoding="utf-8")).get("scripts", {})
        except ValueError:
            scripts = {}
        runner = "npm run"
        for lock, tool in (("pnpm-lock.yaml", "pnpm run"), ("yarn.lock", "yarn run"), ("bun.lockb", "bun run"), ("bun.lock", "bun run")):
            if (root / lock).exists():
                runner = tool
        wanted = (("test", "tests pass"), ("typecheck", "types check"), ("type-check", "types check"),
                  ("lint", "lint is clean"), ("build", "the build works"))
        for script, proves in wanted:
            if script in scripts and "no test specified" not in scripts[script]:
                add(script.replace("type-check", "typecheck"), f"{runner} {script}", proves)

    pyproject = root / "pyproject.toml"
    py_text = pyproject.read_text(encoding="utf-8", errors="replace") if pyproject.exists() else ""
    if (root / "pytest.ini").exists() or "pytest" in py_text or (root / "tests").is_dir() and (pyproject.exists() or (root / "setup.py").exists()):
        add("test", "python3 -m pytest -q", "tests pass")
    if "ruff" in py_text or (root / "ruff.toml").exists():
        add("lint", "ruff check .", "lint is clean")
    if "mypy" in py_text or (root / "mypy.ini").exists():
        add("typecheck", "mypy .", "types check")

    if (root / "Cargo.toml").exists():
        add("test", "cargo test", "tests pass")
        add("build", "cargo check", "the code compiles")
    if (root / "go.mod").exists():
        add("test", "go test ./...", "tests pass")
        add("lint", "go vet ./...", "vet is clean")

    makefile = root / "Makefile"
    if makefile.exists():
        text = makefile.read_text(encoding="utf-8", errors="replace")
        for target, proves in (("test", "tests pass"), ("lint", "lint is clean"), ("build", "the build works")):
            if any(line.startswith(f"{target}:") for line in text.splitlines()):
                add(target, f"make {target}", proves)
    return found


def load_checks(root):
    path = root / STATE / "checks.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get("checks", [])


def run_check(root, check, timeout):
    command = check["command"]
    record = {"check": check["name"], "command": command, "proves": check.get("proves", ""),
              "started": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
    record["commit"], record["tree"], record["dirty"] = code_state(root)
    try:
        program = shlex.split(command)[0]
    except (ValueError, IndexError):
        program = ""
    if not program or shutil.which(program) is None:
        record.update(status="unavailable", exit_code=None, seconds=0, tail=[f"command not found: {program or command}"])
        return record
    begin = datetime.datetime.now()
    try:
        done = subprocess.run(command, shell=True, cwd=root, capture_output=True, text=True, timeout=timeout)
        output, code = (done.stdout + done.stderr), done.returncode
        status = "pass" if code == 0 else "fail"
    except subprocess.TimeoutExpired:
        output, code, status = f"timed out after {timeout} seconds", None, "fail"
    record.update(status=status, exit_code=code, seconds=round((datetime.datetime.now() - begin).total_seconds(), 1),
                  tail=output.strip().splitlines()[-TAIL_LINES:])
    after = code_state(root)
    if after[1] != record["tree"]:
        record["note"] = "the check changed files in the project; the record describes the state before it ran"
    return record


def save(root, record):
    folder = root / STATE / "evidence"
    folder.mkdir(parents=True, exist_ok=True)
    ignore = root / STATE / ".gitignore"
    if not ignore.exists():
        ignore.write_text("evidence/\n", encoding="utf-8")
    (folder / f"{record['check']}.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    with (folder / "log.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps(record) + "\n")


def latest(root, name):
    path = root / STATE / "evidence" / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def cmd_detect(root, args):
    found = detect(root)
    target = root / STATE / "checks.json"
    if args.write:
        if not found:
            print("no checks detected; nothing written")
            return 2
        if target.exists() and not args.force:
            print(f"{target.relative_to(root)} already exists; use --force to replace it")
            return 2
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"checks": found}, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {target.relative_to(root)} with {len(found)} checks")
        return 0
    print(json.dumps({"checks": found}, indent=2))
    if not found:
        print("no checks detected: ask the user for the project's test, lint and build commands", file=sys.stderr)
        return 2
    print("proposal only: show it to the user, then run again with --write", file=sys.stderr)
    return 0


def cmd_run(root, args):
    checks = load_checks(root)
    if checks is None:
        print(f"not verified: {STATE}/checks.json does not exist. Run: checks.py detect")
        return 2
    chosen = [c for c in checks if not args.names or c["name"] in args.names]
    unknown = set(args.names) - {c["name"] for c in checks}
    if unknown or not chosen:
        print(f"not verified: no such check: {', '.join(sorted(unknown)) or '(none defined)'}")
        return 2
    records = []
    for check in chosen:
        print(f"running {check['name']}: {check['command']}", flush=True)
        record = run_check(root, check, args.timeout)
        save(root, record)
        records.append(record)
    return report(records, {r["check"]: "fresh" for r in records})


def cmd_status(root, args):
    checks = load_checks(root)
    if checks is None:
        print(f"not verified: {STATE}/checks.json does not exist. Run: checks.py detect")
        return 2
    _, tree, _ = code_state(root)
    records, age = [], {}
    for check in checks:
        record = latest(root, check["name"])
        if record is None:
            record = {"check": check["name"], "command": check["command"], "status": "missing", "tail": []}
            age[check["name"]] = "never run"
        else:
            age[check["name"]] = "fresh" if tree and record.get("tree") == tree else "stale"
        records.append(record)
    if args.json:
        print(json.dumps([{**r, "age": age[r["check"]]} for r in records], indent=2))
    return report(records, age, quiet=args.json)


def report(records, age, quiet=False):
    failed = [r for r in records if r["status"] == "fail" and age[r["check"]] == "fresh"]
    unproven = [r for r in records if r["status"] in ("unavailable", "missing") or age[r["check"]] != "fresh"]
    if not quiet:
        for r in records:
            label = r["status"] if age[r["check"]] == "fresh" else f"{r['status']} ({age[r['check']]})"
            print(f"  {r['check']:12} {label:22} exit {r.get('exit_code')}  {r.get('seconds', '-')}s  {r['command']}")
        for r in failed:
            print(f"\n--- {r['check']} failed; last lines:")
            print("\n".join(r["tail"]))
        state = records[0].get("commit") if records else None
        if state:
            dirty = " with uncommitted changes" if records[0].get("dirty") else ""
            print(f"\ncode state: commit {state[:10]}{dirty}")
        elif records and "commit" in records[0]:
            print("\ncode state: not a git repository with a commit, so these records cannot be reused later")
    if failed:
        print("RESULT fail")
        return 1
    if unproven:
        print("RESULT not verified: " + ", ".join(f"{r['check']} ({age[r['check']] if r['status'] not in ('unavailable', 'missing') else r['status']})" for r in unproven))
        return 2
    print("RESULT pass")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path.cwd(), help="project folder (default: current folder)")
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("detect", help="propose checks from the project's files")
    p.add_argument("--write", action="store_true", help="save the proposal to .mstack/checks.json")
    p.add_argument("--force", action="store_true", help="replace an existing checks.json")
    p = sub.add_parser("run", help="run checks and record the results")
    p.add_argument("names", nargs="*", help="check names (default: all)")
    p.add_argument("--timeout", type=int, default=900, help="seconds allowed per check (default 900)")
    p = sub.add_parser("status", help="show the latest record for each check")
    p.add_argument("--json", action="store_true", help="print the records as JSON")
    args = parser.parse_args()
    root = args.root.resolve()
    return {"detect": cmd_detect, "run": cmd_run, "status": cmd_status}[args.action](root, args)


if __name__ == "__main__":
    sys.exit(main())

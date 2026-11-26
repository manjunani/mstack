#!/usr/bin/env python3
"""Collect the facts of what a task really changed, for an explanation built on evidence.

  start     mark the beginning of a task (records the current commit, and optionally its scope)
  summary   print what changed since then: files, lines, commits, files outside the scope, checks on record

`summary` with no recorded start uses uncommitted changes if there are any, otherwise the last commit,
and says which range it used. It reads only; it changes no project file.
Exit codes: 0 = facts printed, 2 = blocked: no git repository or nothing to describe.
"""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
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


def git(root, *args):
    try:
        out = subprocess.run([GIT, "-C", str(root), *args], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout if out.returncode == 0 else None


def tree_state(root):
    head = git(root, "rev-parse", "HEAD")
    if head is None:
        return None
    scope = ["--", ".", f":(exclude){STATE}"]
    status = git(root, "status", "--porcelain=v1", "-uall", *scope) or ""
    diff = git(root, "diff", "HEAD", *scope) or ""
    digest = hashlib.sha256((head + status + diff).encode("utf-8", "replace"))
    for line in status.splitlines():
        if line.startswith("?? "):
            try:
                stat = (root / line[3:].strip().strip('"')).stat()
                digest.update(f"{line[3:]}:{stat.st_size}:{stat.st_mtime_ns}".encode())
            except OSError:
                pass
    return digest.hexdigest()[:16]


def cmd_start(root, args):
    head = git(root, "rev-parse", "HEAD")
    if head is None:
        print("blocked: not a git repository with a commit")
        return 2
    (root / STATE).mkdir(exist_ok=True)
    data = {"commit": head.strip(), "started": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "task": args.task, "scope": args.scope}
    (root / STATE / "task-start.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"task start recorded at commit {head.strip()[:10]}" + (f", scope: {', '.join(args.scope)}" if args.scope else ""))
    return 0


def cmd_summary(root, args):
    head = git(root, "rev-parse", "HEAD")
    if head is None:
        print("blocked: not a git repository with a commit")
        return 2
    head = head.strip()
    start_file = root / STATE / "task-start.json"
    start = json.loads(start_file.read_text(encoding="utf-8")) if start_file.exists() else None
    exclude = ["--", ".", f":(exclude){STATE}"]
    dirty = [l for l in (git(root, "status", "--porcelain", *exclude) or "").splitlines() if l.strip()]
    if args.since:
        base, how = args.since, f"the commit you gave ({args.since})"
    elif start:
        base, how = start["commit"], f"the recorded task start ({start['commit'][:10]}, {start['started']})"
    elif dirty:
        base, how = head, "uncommitted changes only (no task start was recorded)"
    else:
        base, how = f"{head}~1", "the last commit only (no task start was recorded and nothing is uncommitted)"
    if git(root, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}") is None:
        print(f"blocked: cannot resolve {base}. Give a range with --since <commit>.")
        return 2

    numstat = (git(root, "diff", "--numstat", base, *exclude) or "").splitlines()
    files = []
    for line in numstat:
        added, removed, path = line.split("\t", 2)
        files.append({"path": path, "added": added, "removed": removed})
    for line in dirty:
        if line.startswith("?? "):
            path = line[3:].strip().strip('"')
            try:
                count = sum(1 for _ in (root / path).open("rb")) if (root / path).is_file() else 0
            except OSError:
                count = 0
            files.append({"path": path, "added": str(count), "removed": "0", "new": True})
    commits = (git(root, "log", "--oneline", f"{base}..HEAD") or "").splitlines()
    scope = (start or {}).get("scope") or []
    outside = [f["path"] for f in files if scope and not any(f["path"] == s.rstrip("/") or f["path"].startswith(s.rstrip("/") + "/") for s in scope)]

    current = tree_state(root)
    records = []
    folder = root / STATE / "evidence"
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        record = json.loads(path.read_text(encoding="utf-8"))
        fresh = bool(current) and record.get("tree") == current
        records.append({"check": record["check"], "status": record["status"], "command": record["command"],
                        "current": fresh, "started": record.get("started")})

    facts = {"range": how, "task": (start or {}).get("task"), "files": files, "commits": commits, "uncommitted_files": len(dirty),
             "scope": scope, "outside_scope": outside, "checks": records}
    if args.json:
        print(json.dumps(facts, indent=2))
        return 0 if files or commits else 2

    print(f"RANGE: {how}")
    if facts["task"]:
        print(f"TASK: {facts['task']}")
    print(f"\nFILES CHANGED ({len(files)}):")
    for f in files:
        print(f"  {'new ' if f.get('new') else ''}{f['path']}  +{f['added']} -{f['removed']}")
    print(f"\nCOMMITS IN RANGE ({len(commits)}):")
    for line in commits:
        print(f"  {line}")
    print(f"\nUNCOMMITTED: {len(dirty)} files")
    if scope:
        print(f"\nSTATED SCOPE: {', '.join(scope)}")
        print(f"CHANGED OUTSIDE SCOPE ({len(outside)}):" + ("" if outside else " none"))
        for path in outside:
            print(f"  {path}")
    print(f"\nCHECKS ON RECORD ({len(records)}):" + ("" if records else " none. Nothing in this change is verified by a record."))
    for r in records:
        tag = "made on the current code" if r["current"] else "STALE: made on different code, does not count"
        print(f"  {r['check']}: {r['status']} ({tag})  [{r['command']}]")
    if not files and not commits:
        print("\nblocked: nothing changed in this range")
        return 2
    print("\nBuild the explanation from these facts only. Anything not listed here is inferred or unknown, and is said to be.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path.cwd(), help="project folder (default: current folder)")
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("start", help="mark the beginning of a task")
    p.add_argument("--task", default="", help="one line on what the task is")
    p.add_argument("--scope", action="append", default=[], help="a folder or file the task is meant to touch; repeat as needed")
    p = sub.add_parser("summary", help="print what changed")
    p.add_argument("--since", help="start from this commit instead of the recorded task start")
    p.add_argument("--json", action="store_true", help="print the facts as JSON")
    args = parser.parse_args()
    return {"start": cmd_start, "summary": cmd_summary}[args.action](args.root.resolve(), args)


if __name__ == "__main__":
    sys.exit(main())

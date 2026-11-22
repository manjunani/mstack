#!/usr/bin/env python3
"""Keep file edits inside one folder until the lock is released.

  set FOLDER   allow edits only under FOLDER
  status       show the lock, if any
  test PATH    say whether an edit to PATH would be allowed (changes nothing)
  release      remove the lock

The lock is a file, .mstack/scope-lock.json. In Claude Code the mstack-core guard hook reads it and
denies Write and Edit calls outside the folder. Shell commands are not parsed, so the lock does not
stop a script that writes files. Exit codes: 0 = done or allowed, 1 = denied, 2 = blocked or no lock.
"""
import argparse
import datetime
import json
import pathlib
import sys
import tempfile

STATE = ".mstack"


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def lock_file(project):
    return project / STATE / "scope-lock.json"


def read_lock(project):
    path = lock_file(project)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def allowed(project, lock, raw):
    """Return (bool, reason). The same rule the guard hook applies."""
    path = pathlib.Path(raw).expanduser()
    path = (path if path.is_absolute() else project / path).resolve()
    root = pathlib.Path(lock["root"])
    temps = {pathlib.Path(tempfile.gettempdir()).resolve(), pathlib.Path("/tmp").resolve()}
    if path == root or root in path.parents:
        return True, "inside the locked folder"
    if (project / STATE) in path.parents:
        return True, f"inside {STATE}, which stays writable"
    if any(t == path or t in path.parents for t in temps):
        return True, "inside a temporary folder"
    return False, f"outside the locked folder {root}"


def log(project, line):
    with (project / STATE / "scope-lock.log").open("a", encoding="utf-8") as handle:
        handle.write(f"{now()} {line}\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", type=pathlib.Path, default=pathlib.Path.cwd(), help="project folder (default: current folder)")
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("set", help="lock edits to one folder")
    p.add_argument("folder")
    p.add_argument("--reason", default="")
    sub.add_parser("status", help="show the lock")
    sub.add_parser("test", help="would an edit to this path be allowed?").add_argument("path")
    sub.add_parser("release", help="remove the lock")
    args = parser.parse_args()
    project = args.project.resolve()
    lock = read_lock(project)

    if args.action == "set":
        folder = pathlib.Path(args.folder).expanduser()
        folder = (folder if folder.is_absolute() else project / folder).resolve()
        if not folder.is_dir():
            print(f"blocked: {folder} is not a folder")
            return 2
        if folder != project and project not in folder.parents:
            print(f"blocked: {folder} is outside the project {project}")
            return 2
        (project / STATE).mkdir(exist_ok=True)
        lock_file(project).write_text(json.dumps({"root": str(folder), "set": now(), "reason": args.reason}, indent=2) + "\n", encoding="utf-8")
        log(project, f"set {folder} reason={args.reason!r}")
        print(f"locked: edits are allowed only under {folder}\nrelease with: lock.py release")
        return 0
    if lock is None:
        print("no lock is set")
        return 2
    if args.action == "status":
        print(f"locked to {lock['root']} since {lock['set']}" + (f" ({lock['reason']})" if lock.get("reason") else ""))
        return 0
    if args.action == "test":
        ok, reason = allowed(project, lock, args.path)
        print(f"{'allowed' if ok else 'denied'}: {args.path} is {reason}")
        return 0 if ok else 1
    lock_file(project).unlink()
    log(project, f"release {lock['root']}")
    print(f"released: edits are no longer limited to {lock['root']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

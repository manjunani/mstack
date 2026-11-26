#!/usr/bin/env python3
"""Remove files and folders from a project so that the removal can be undone.

  plan TARGET...   list exactly what would go, what refers to it, and what git cannot bring back
  apply ID         move the planned targets into .mstack/trash/ID/ and check the copy is complete
  undo ID          move everything back
  purge ID         delete the trash copy for good (needs --confirm ID)
  list             show manifests and their state

Nothing is hard-deleted except by `purge`. Targets must be inside the project folder.
Exit codes: 0 = done, 1 = refused or failed, 2 = blocked: bad input or nothing to do.
"""
import argparse
import datetime
import json
import os
import pathlib
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
REGENERABLE = {"node_modules", "dist", "build", "target", ".next", ".nuxt", ".turbo", ".cache", "__pycache__",
               ".pytest_cache", ".mypy_cache", ".ruff_cache", ".venv", "venv", "coverage", ".parcel-cache", "DerivedData"}


def git(root, *args):
    try:
        out = subprocess.run([GIT, "-C", str(root), *args], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout if out.returncode in (0, 1) else None


def measure(path):
    """Return (file count, bytes) without following symlinks."""
    if path.is_symlink() or path.is_file():
        return 1, path.lstat().st_size
    count = size = 0
    for folder, _, files in os.walk(path, followlinks=False):
        for name in files:
            try:
                size += os.lstat(os.path.join(folder, name)).st_size
                count += 1
            except OSError:
                pass
    return count, size


def lines(text):
    return [line for line in (text or "").splitlines() if line.strip()]


def refuse_reason(root, raw, path):
    home = pathlib.Path.home().resolve()
    if not path.exists() and not path.is_symlink():
        return "does not exist"
    if path == root:
        return "is the project folder itself"
    if path in (home, pathlib.Path(path.anchor)):
        return "is the home folder or the file system root"
    if root not in path.parents:
        return "is outside the project folder; this version only handles files inside it"
    rel = path.relative_to(root)
    if rel.parts[0] == ".git":
        return "is inside .git; use git commands for git objects"
    if rel.parts[0] == STATE:
        return f"is inside {STATE}; use undo or purge"
    return None


def describe(root, raw):
    given = pathlib.Path(raw).expanduser()
    path = (given if given.is_absolute() else root / given)
    path = path.parent.resolve() / path.name  # resolve the folder, keep a symlink target as the link itself
    reason = refuse_reason(root, raw, path)
    if reason:
        return {"target": raw, "refused": reason}
    rel = str(path.relative_to(root))
    count, size = measure(path)
    tracked = lines(git(root, "ls-files", "--", rel))
    untracked = lines(git(root, "ls-files", "--others", "--exclude-standard", "--", rel))
    ignored = lines(git(root, "ls-files", "--others", "--ignored", "--exclude-standard", "--", rel))
    modified = lines(git(root, "status", "--porcelain", "--", rel))
    in_git = git(root, "rev-parse", "--is-inside-work-tree") is not None
    refs = []
    if in_git and path.name not in REGENERABLE:
        found = git(root, "grep", "-n", "-I", "-F", "-e", path.name, "--", ".", f":(exclude){rel}")
        refs = lines(found)[:10]
    return {
        "target": raw, "path": rel, "kind": "folder" if path.is_dir() and not path.is_symlink() else "file",
        "files": count, "bytes": size,
        "regenerable": path.name in REGENERABLE,
        "git": {"repository": in_git, "tracked": len(tracked), "untracked": len(untracked), "ignored": len(ignored),
                "uncommitted_changes": len([m for m in modified if not m.startswith(("??", "!!"))])},
        "not_recoverable_from_git": count if not in_git else len(untracked) + len(ignored) + len([m for m in modified if not m.startswith(("??", "!!"))]),
        "referred_to_by": refs,
    }


def human(size):
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


def manifest_path(root, ident):
    return root / STATE / "delete" / f"{ident}.json"


def load(root, ident):
    path = manifest_path(root, ident)
    if not path.exists():
        print(f"blocked: no manifest {ident}. Run: manifest.py list")
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def store(root, manifest):
    path = manifest_path(root, manifest["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    ignore = root / STATE / ".gitignore"
    existing = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
    for entry in ("trash/", "delete/"):
        if entry not in existing.splitlines():
            existing += entry + "\n"
    ignore.write_text(existing, encoding="utf-8")
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def show(manifest):
    print(f"manifest {manifest['id']}  state: {manifest['state']}  reason: {manifest.get('reason') or '(none given)'}")
    for item in manifest["items"]:
        if "refused" in item:
            print(f"  REFUSED {item['target']}: {item['refused']}")
            continue
        g = item["git"]
        tag = " (regenerable)" if item["regenerable"] else ""
        print(f"  {item['path']}{tag}: {item['kind']}, {item['files']} files, {human(item['bytes'])}")
        if g["repository"]:
            print(f"      git: {g['tracked']} tracked, {g['untracked']} untracked, {g['ignored']} ignored, {g['uncommitted_changes']} with uncommitted changes")
        else:
            print("      git: not a repository, so nothing here can be restored from history")
        if item["not_recoverable_from_git"] and not item["regenerable"]:
            print(f"      WARNING: {item['not_recoverable_from_git']} files exist only here; git cannot bring them back")
        for ref in item["referred_to_by"]:
            print(f"      referred to by: {ref[:140]}")


def cmd_plan(root, args):
    items = [describe(root, raw) for raw in args.targets]
    stamp = datetime.datetime.now(datetime.timezone.utc)
    ident = stamp.strftime("%Y%m%d-%H%M%S") + f"{stamp.microsecond // 1000:03d}"  # sorts by time
    while manifest_path(root, ident).exists():
        ident = ident[:-3] + f"{(int(ident[-3:]) + 1) % 1000:03d}"
    manifest = {"id": ident, "state": "planned", "created": stamp.isoformat(timespec="seconds"), "reason": args.reason, "items": items}
    refused = [i for i in items if "refused" in i]
    if refused:
        manifest["state"] = "refused"
        show(manifest)
        print("RESULT blocked: nothing was planned. Remove the refused targets and plan again.")
        return 1
    store(root, manifest)
    show(manifest)
    total = sum(i["files"] for i in items)
    print(f"\nNothing has been removed. {total} files in {len(items)} targets would move to {STATE}/trash/{ident}/.")
    print(f"Show this to the user. After a clear yes: manifest.py apply {ident}")
    return 0


def cmd_apply(root, args):
    manifest = load(root, args.id)
    if manifest is None:
        return 2
    if manifest["state"] != "planned":
        print(f"blocked: manifest {args.id} is '{manifest['state']}', not 'planned'")
        return 2
    for item in manifest["items"]:
        source = root / item["path"]
        if not source.exists() and not source.is_symlink():
            print(f"RESULT fail: {item['path']} no longer exists. Nothing moved. Plan again.")
            return 1
        if measure(source) != (item["files"], item["bytes"]):
            print(f"RESULT fail: {item['path']} changed since the plan. Nothing moved. Plan again and show the user the new numbers.")
            return 1
    trash = root / STATE / "trash" / args.id
    moved = []
    try:
        for item in manifest["items"]:
            dest = trash / item["path"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(root / item["path"]), str(dest))
            moved.append(item)
            if measure(dest) != (item["files"], item["bytes"]):
                raise OSError(f"copy of {item['path']} is incomplete")
    except OSError as exc:
        for item in reversed(moved):
            shutil.move(str(trash / item["path"]), str(root / item["path"]))
        print(f"RESULT fail: {exc}. Everything was moved back.")
        return 1
    manifest["state"] = "applied"
    manifest["applied"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    store(root, manifest)
    print(f"moved {len(moved)} targets to {STATE}/trash/{args.id}/ and checked each copy is complete")
    print(f"undo:  manifest.py undo {args.id}")
    print(f"free the disk space later, for good:  manifest.py purge {args.id} --confirm {args.id}")
    print("RESULT pass")
    return 0


def cmd_undo(root, args):
    manifest = load(root, args.id)
    if manifest is None:
        return 2
    if manifest["state"] != "applied":
        print(f"blocked: manifest {args.id} is '{manifest['state']}'; only an applied one can be undone")
        return 2
    trash = root / STATE / "trash" / args.id
    clash = [i["path"] for i in manifest["items"] if (root / i["path"]).exists()]
    if clash:
        print(f"RESULT fail: something already exists at {', '.join(clash)}. Nothing moved.")
        return 1
    for item in manifest["items"]:
        (root / item["path"]).parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(trash / item["path"]), str(root / item["path"]))
    manifest["state"] = "undone"
    store(root, manifest)
    print(f"restored {len(manifest['items'])} targets\nRESULT pass")
    return 0


def cmd_purge(root, args):
    manifest = load(root, args.id)
    if manifest is None:
        return 2
    if manifest["state"] != "applied":
        print(f"blocked: manifest {args.id} is '{manifest['state']}'; only an applied one can be purged")
        return 2
    if args.confirm != args.id:
        print(f"blocked: this cannot be undone. The user must ask for it; then run: manifest.py purge {args.id} --confirm {args.id}")
        return 2
    trash = root / STATE / "trash" / args.id
    count, size = measure(trash) if trash.exists() else (0, 0)
    shutil.rmtree(trash, ignore_errors=False)
    manifest["state"] = "purged"
    store(root, manifest)
    print(f"deleted {count} files, {human(size)}, for good\nRESULT pass")
    return 0


def cmd_list(root, args):
    folder = root / STATE / "delete"
    found = sorted(folder.glob("*.json")) if folder.is_dir() else []
    for path in found:
        m = json.loads(path.read_text(encoding="utf-8"))
        paths = ", ".join(i.get("path", i["target"]) for i in m["items"])
        print(f"{m['id']}  {m['state']:8}  {paths}")
    if not found:
        print("no manifests")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path.cwd(), help="project folder (default: current folder)")
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("plan", help="list what would be removed; removes nothing")
    p.add_argument("targets", nargs="+")
    p.add_argument("--reason", default="", help="why these are being removed")
    for name, text in (("apply", "move the planned targets to the trash"), ("undo", "move them back")):
        sub.add_parser(name, help=text).add_argument("id")
    p = sub.add_parser("purge", help="delete a trash copy for good")
    p.add_argument("id")
    p.add_argument("--confirm", default="", help="repeat the manifest id to confirm")
    sub.add_parser("list", help="show manifests")
    args = parser.parse_args()
    root = args.root.resolve()
    return {"plan": cmd_plan, "apply": cmd_apply, "undo": cmd_undo, "purge": cmd_purge, "list": cmd_list}[args.action](root, args)


if __name__ == "__main__":
    sys.exit(main())

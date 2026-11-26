#!/usr/bin/env python3
"""Checks for finishing a branch: merge it locally, push it and open a pull request, or keep it.

  check      confirm the base branch, that the tree is clean, how far the branch is ahead and behind,
             and run the full suite on the tree to be integrated. Saves a snapshot of what it saw
  recheck    right before a push, a PR create or a merge: compare the repository with the snapshot and
             refuse if anything moved (new commits, a dirty tree, a moved base, another branch)
  merged     after a local merge: run the suite on the merged result and say whether the branch can be
             deleted safely (all of its commits are in the base)

The snapshot is .mstack/land/snapshot.json (git-ignored).

Exit codes: 0 = pass, 1 = fail (dirty tree, failing suite, state moved, branch is the base), 2 = not verified
or blocked (no base found, suite not given, not a git repository). The last line is the RESULT.
This script runs the suite command it is given and git commands that only read. It never pushes, merges or deletes.
"""
import argparse
import datetime
import json
import os
import pathlib
import signal
import subprocess
import sys
import time

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
SCOPE = ["--", ".", f":(exclude){STATE}"]


def git(root, *args):
    try:
        out = subprocess.run([GIT, "-C", str(root), *args], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    return out.returncode, out.stdout.strip() if out.returncode == 0 else (out.stdout + out.stderr).strip()


def run_shell(command, cwd, timeout):
    begin = time.monotonic()
    try:
        proc = subprocess.Popen(command, shell=True, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors="replace", start_new_session=True)
    except OSError as exc:
        return 127, str(exc), 0.0
    try:
        out, _ = proc.communicate(timeout=timeout)
        code = proc.returncode
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            proc.kill()
        out, _ = proc.communicate()
        out, code = (out or "") + f"\n(timed out after {timeout} seconds)", None
    return code, out or "", round(time.monotonic() - begin, 1)


def resolve(root, ref):
    code, out = git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    return out if code == 0 and out else None


def find_base(root, current):
    code, out = git(root, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    names = [out.split("/", 1)[-1]] if code == 0 and out else []
    for name in names + ["main", "master", "trunk", "develop"]:
        if resolve(root, name):
            return name
    return None


def snapshot(root, base):
    _, branch = git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    _, status = git(root, "status", "--porcelain=v1", *SCOPE)
    _, upstream = git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    return {"branch": branch or None, "head": resolve(root, "HEAD"), "base": base, "base_commit": resolve(root, base),
            "dirty": [line for line in status.splitlines() if line.strip()],
            "upstream": upstream if upstream and "fatal" not in upstream and "no upstream" not in upstream else None}


def path_of(root):
    folder = root / STATE / "land"
    folder.mkdir(parents=True, exist_ok=True)
    ignore = root / STATE / ".gitignore"
    known = ignore.read_text(encoding="utf-8").splitlines() if ignore.exists() else []
    if "land/" not in known:
        with ignore.open("a", encoding="utf-8") as handle:
            handle.write("land/\n")
    return folder / "snapshot.json"


def run_suite(root, suite, timeout):
    code, output, seconds = run_shell(suite, root, timeout)
    last = output.strip().splitlines()[-15:]
    shown = "timed out" if code is None else f"exit {code}"
    print(f"suite: {suite}\n  {shown} in {seconds}s")
    if code != 0:
        print("--- last lines:")
        print("\n".join(last))
    return code


def cmd_check(root, args):
    snap = snapshot(root, "")
    if snap["branch"] is None:
        print("RESULT blocked: no branch is checked out (detached HEAD); check out the branch to finish")
        return 2
    base = args.base or find_base(root, snap["branch"])
    if base is None or resolve(root, base) is None:
        print(f"RESULT blocked: the base branch could not be found{' (' + args.base + ' is not a commit)' if args.base else ''}; give --base <branch>")
        return 2
    snap = snapshot(root, base)
    problems = []
    print(f"branch: {snap['branch']}  base: {base} ({'given' if args.base else 'found by itself; confirm it with the user'})")
    if snap["branch"] == base:
        problems.append(f"the branch to finish is the base branch itself ({base}); there is nothing to land")
    _, ahead = git(root, "rev-list", "--count", f"{base}..HEAD")
    _, behind = git(root, "rev-list", "--count", f"HEAD..{base}")
    print(f"  {ahead} commits ahead of {base}, {behind} behind")
    if ahead == "0" and snap["branch"] != base:
        problems.append(f"the branch has no commits that {base} lacks")
    if snap["dirty"]:
        problems.append(f"the tree has {len(snap['dirty'])} uncommitted changes: {', '.join(l[3:] for l in snap['dirty'][:6])}")
    print(f"  upstream: {snap['upstream'] or 'none (a push would need -u origin ' + snap['branch'] + ')'}")
    _, log = git(root, "log", "--format=  %h %s", f"{base}..HEAD")
    if log:
        print(log)
    if problems:
        for problem in problems:
            print(f"FAIL {problem}")
        print("RESULT fail: the branch is not ready to land")
        return 1
    if not args.suite:
        path_of(root).write_text(json.dumps({**snap, "suite": None, "at": datetime.datetime.now().isoformat()}, indent=2), encoding="utf-8")
        print("RESULT not verified: no suite command given (--suite); the tree to be integrated was not tested")
        return 2
    code = run_suite(root, args.suite, args.timeout)
    snap["suite"] = {"command": args.suite, "exit_code": code, "head": snap["head"]}
    path_of(root).write_text(json.dumps({**snap, "at": datetime.datetime.now().isoformat()}, indent=2), encoding="utf-8")
    if code in (126, 127):
        print("RESULT not verified: the suite command could not be run")
        return 2
    if code != 0:
        print("RESULT fail: the suite fails on the branch; do not land it")
        return 1
    if behind != "0":
        print(f"note: {base} has {behind} commits this branch lacks; the merged result can still fail. 'merged' tests it after a local merge")
    print("snapshot saved; run 'preflight.py recheck' right before any push, PR create or merge")
    print("RESULT pass")
    return 0


def cmd_recheck(root, args):
    path = root / STATE / "land" / "snapshot.json"
    if not path.exists():
        print("RESULT blocked: no snapshot. Run: preflight.py check --suite <command>")
        return 2
    old = json.loads(path.read_text(encoding="utf-8"))
    now = snapshot(root, old["base"])
    moved = []
    for key, label in (("branch", "branch"), ("head", "branch tip"), ("base_commit", f"base {old['base']}"), ("upstream", "upstream")):
        if old.get(key) != now.get(key):
            moved.append(f"{label}: was {str(old.get(key))[:12]}, now {str(now.get(key))[:12]}")
    if now["dirty"]:
        moved.append(f"the tree has uncommitted changes: {', '.join(l[3:] for l in now['dirty'][:6])}")
    if not old.get("suite") or old["suite"].get("exit_code") != 0 or old["suite"].get("head") != now["head"]:
        moved.append("no passing suite run recorded for this exact commit")
    if args.fetch_remote:
        _, remote_tip = git(root, "ls-remote", "origin", f"refs/heads/{now['branch']}")
        tip = remote_tip.split()[0] if remote_tip else None
        if tip and tip != now["head"]:
            code, _ = git(root, "merge-base", "--is-ancestor", tip, "HEAD")
            if code != 0:
                moved.append(f"origin/{now['branch']} has commits that are not here ({tip[:12]}); a push would be rejected or would overwrite them")
    for line in moved:
        print(f"MOVED {line}")
    if moved:
        print("RESULT fail: the repository is not as it was checked; run 'preflight.py check' again before going on")
        return 1
    print(f"unchanged since the check: {now['branch']} at {now['head'][:12]}, base {old['base']} at {now['base_commit'][:12]}, clean tree")
    print("RESULT pass")
    return 0


def cmd_merged(root, args):
    path = root / STATE / "land" / "snapshot.json"
    if not path.exists():
        print("RESULT blocked: no snapshot from 'check'; the branch that was merged is not known")
        return 2
    old = json.loads(path.read_text(encoding="utf-8"))
    _, current = git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    if current != old["base"]:
        print(f"RESULT blocked: run this on {old['base']} after the merge; this is {current or 'a detached HEAD'}")
        return 2
    code, _ = git(root, "merge-base", "--is-ancestor", old["head"], "HEAD")
    if code != 0:
        print(f"RESULT fail: {old['base']} does not contain the branch tip {old['head'][:12]}; the merge did not happen")
        return 1
    code = run_suite(root, args.suite, args.timeout)
    if code in (126, 127):
        print("RESULT not verified: the suite command could not be run")
        return 2
    if code != 0:
        print(f"RESULT fail: the suite fails on the merged {old['base']}; keep the branch and fix this first")
        return 1
    branch_tip = resolve(root, old["branch"]) if old.get("branch") else None
    if branch_tip and branch_tip != old["head"]:
        print(f"note: {old['branch']} moved after the check ({branch_tip[:12]}); it is NOT safe to delete")
    else:
        print(f"every commit of {old['branch']} is in {old['base']}; 'git branch -d {old['branch']}' is safe (git refuses if not)")
    print("RESULT pass")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("check", help="base, clean tree, suite; save a snapshot")
    one.add_argument("--base", help="base branch (default: origin's default, else main, master, trunk, develop)")
    one.add_argument("--suite", help="the project's full test command")
    one.add_argument("--timeout", type=int, default=3600)
    one.set_defaults(run=cmd_check)
    two = sub.add_parser("recheck", help="refuse if anything moved since the check")
    two.add_argument("--fetch-remote", action="store_true", help="also ask origin for the branch's tip (uses the network)")
    two.set_defaults(run=cmd_recheck)
    three = sub.add_parser("merged", help="suite on the merged result; is the branch safe to delete")
    three.add_argument("--suite", required=True)
    three.add_argument("--timeout", type=int, default=3600)
    three.set_defaults(run=cmd_merged)
    args = parser.parse_args()
    code, top = git(pathlib.Path.cwd(), "rev-parse", "--show-toplevel")
    if code != 0:
        print("RESULT blocked: not inside a git repository")
        return 2
    return args.run(pathlib.Path(top), args)


if __name__ == "__main__":
    sys.exit(main())

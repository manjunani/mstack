#!/usr/bin/env python3
"""Show that a test can catch the bug it protects against: it passes with the change and fails without it.

  run       1. run the test with the change in place            (must pass)
            2. put the change aside, run the test again          (must fail)
            3. put the change back, run the test a third time    (must pass)
            The script records the three exit codes itself and checks that every file is back as it was.
  restore   put the files back after a run that was killed half way
  status    show the last record

What "the change" is:
  default            every file that differs from HEAD or is new, except files that look like tests
  --fix PATH ...     only these files or folders
  --keep PATTERN ... leave these in place as well (the test file is kept by default when it looks like a test)
  --against REF      compare with this commit instead of HEAD; for a fix that is already committed,
                     give the commit before the fix (for example HEAD~1)

Putting a change aside means: a file that exists in REF gets REF's content for the middle run; a file that is
new is moved out of the way. Before anything is touched every file is copied to .mstack/prove/<id>/files/ and a
journal is written, so "restore" can finish the job after a crash. The index and the stash are never used.
A file comes back with the same bytes and a newer modification time, so that build tools notice both swaps.

Exit codes: 0 = proven (pass, fail, pass); 1 = not proven (the test passes without the change, fails with it,
or fails for another reason); 2 = not verified or blocked (the test could not run, timed out, or there is
nothing to put aside). The last line is the RESULT.
"""
import argparse
import datetime
import fnmatch
import hashlib
import json
import os
import pathlib
import re
import shutil
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
FOLDER = "prove"
# Python bytecode is left out: a test run rewrites tracked .pyc files, which is not a change to put back.
SCOPE = ["--", ".", f":(exclude){STATE}", ":(exclude,glob)**/__pycache__/**", ":(exclude,glob)**/*.pyc"]
TESTLIKE = re.compile(r"(^|/)(tests?|__tests__|specs?|e2e|testing)/|(^|/)test_[^/]+$|_test\.[^/.]+$|\.(test|spec)\.[^/]+$|"
                      r"(^|/)conftest\.py$|[a-z0-9]Tests?\.[^/.]+$")


class Interrupted(Exception):
    pass


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def git_bytes(root, *args):
    try:
        out = subprocess.run([GIT, "-C", str(root), *args], capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc).encode()
    return out.returncode, out.stdout if out.returncode == 0 else out.stdout + out.stderr


def git(root, *args):
    code, out = git_bytes(root, *args)
    return code, out.decode("utf-8", "replace")


def run_shell(command, cwd, timeout):
    """Return (exit code or None on timeout, output, seconds). The child gets its own process group."""
    begin = time.monotonic()
    try:
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        proc = subprocess.Popen(command, shell=True, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors="replace", start_new_session=True, env=env)
    except OSError as exc:
        return 127, str(exc), 0.0
    try:
        out, _ = proc.communicate(timeout=timeout)
        code = proc.returncode
    except subprocess.TimeoutExpired:
        kill_group(proc)
        out, _ = proc.communicate()
        out, code = (out or "") + f"\n(timed out after {timeout} seconds)", None
    except BaseException:
        kill_group(proc)
        raise
    return code, out or "", round(time.monotonic() - begin, 1)


def kill_group(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        try:
            proc.kill()
        except OSError:
            pass


def sha(path):
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def tree_print(root):
    """A fingerprint of what git sees: status and the diff against HEAD."""
    _, status = git(root, "status", "--porcelain=v1", "-uall", *SCOPE)
    _, diff = git_bytes(root, "diff", "--binary", "HEAD", *SCOPE)
    return hashlib.sha256(status.encode() + diff).hexdigest()


def matches(path, patterns):
    for pattern in patterns:
        clean = pattern.rstrip("/")
        if path == clean or path.startswith(clean + "/") or fnmatch.fnmatch(path, pattern):
            return True
    return False


def state_dir(root):
    folder = root / STATE / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    ignore = root / STATE / ".gitignore"
    known = ignore.read_text(encoding="utf-8").splitlines() if ignore.exists() else []
    if f"{FOLDER}/" not in known:
        with ignore.open("a", encoding="utf-8") as handle:
            handle.write(f"{FOLDER}/\n")
    return folder


def write_json(path, data):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def later_than(path, earlier):
    """Give the file a modification time in a later whole second than `earlier`, so tools that cache by
    time and size (Python bytecode, make) see that the content changed."""
    stamp = max(time.time(), int(earlier) + 1.0)
    try:
        os.utime(path, (stamp, stamp))
    except OSError:
        pass


def mtime(path):
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def put_back(root, journal):
    """Restore every file from its backup and remove what the middle run created. Return a list of problems."""
    problems = []
    for item in journal["files"]:
        target = root / item["path"]
        if item["existed"]:
            backup = pathlib.Path(journal["backup"]) / item["path"]
            seen = max(mtime(target), mtime(backup))
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup, target)
                later_than(target, seen)
            except OSError as exc:
                problems.append(f"{item['path']}: {exc}")
                continue
            if sha(target) != item["sha"]:
                problems.append(f"{item['path']}: content differs from the backup")
        elif target.exists():
            try:
                target.unlink()
            except OSError as exc:
                problems.append(f"{item['path']}: {exc}")
    for folder in reversed(journal.get("made_dirs", [])):
        try:
            (root / folder).rmdir()
        except OSError:
            pass
    return problems


def put_aside(root, journal, against):
    """Give every file of the change the content it has in the commit `against`."""
    for item in journal["files"]:
        target = root / item["path"]
        code, old = git_bytes(root, "show", f"{against}:{item['path']}")
        if code == 0:
            folder = target.parent
            missing = []
            while not folder.exists():
                missing.append(os.path.relpath(folder, root))
                folder = folder.parent
            for made in reversed(missing):
                (root / made).mkdir()
                journal["made_dirs"].append(made)
            seen = mtime(target)
            with open(target, "wb") as handle:
                handle.write(old)
            later_than(target, seen)
            _, entry = git(root, "ls-tree", against, "--", item["path"])
            if entry.startswith("100755"):
                target.chmod(target.stat().st_mode | 0o111)
        elif target.exists():
            target.unlink()


def pick_change(root, args, against):
    code, tracked = git(root, "diff", "--name-only", against, *SCOPE)
    if code != 0:
        return None, None, f"git could not compare with {against}"
    _, untracked = git(root, "ls-files", "--others", "--exclude-standard", *SCOPE)
    candidates = sorted({p for p in tracked.splitlines() + untracked.splitlines() if p})
    keep = list(args.keep or [])
    if args.fix:
        for wanted in args.fix:
            if not matches_any(candidates, wanted):
                return None, None, f"--fix {wanted}: no file there differs from {args.against}"
        change = [p for p in candidates if matches(p, args.fix) and not matches(p, keep)]
    else:
        change = [p for p in candidates if not TESTLIKE.search(p) and not matches(p, keep)]
    kept = [p for p in candidates if p not in change]
    return change, kept, None


def matches_any(candidates, pattern):
    return any(matches(p, [pattern]) for p in candidates)


def cmd_run(root, args):
    folder = state_dir(root)
    journal_path = folder / "journal.json"
    if journal_path.exists():
        pending = json.loads(journal_path.read_text(encoding="utf-8"))
        if pending.get("state") == "aside":
            print(f"RESULT blocked: an earlier run stopped half way and its files are still put aside. Run: prove.py restore")
            return 2
    code, against = git(root, "rev-parse", "--verify", f"{args.against}^{{commit}}")
    if code != 0:
        print(f"RESULT blocked: {args.against} is not a commit")
        return 2
    against = against.strip()
    change, kept, problem = pick_change(root, args, against)
    if problem:
        print(f"RESULT blocked: {problem}")
        return 2
    if not change:
        print(f"nothing to put aside: no file besides tests differs from {args.against}.")
        print("RESULT blocked: name the change with --fix, or, if the fix is already committed, give --against <the commit before it>")
        return 2
    links = [p for p in change if (root / p).is_symlink() or (root / p).is_dir()]
    if links:
        print(f"RESULT blocked: these are links or folders, not plain files: {', '.join(links)}. Name plain files with --fix")
        return 2

    ident = datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + f"-{os.getpid()}"
    backup = folder / ident / "files"
    journal = {"id": ident, "state": "copied", "against": against, "backup": str(backup), "files": [], "made_dirs": [], "at": now()}
    for path in change:
        source = root / path
        item = {"path": path, "existed": source.exists(), "sha": sha(source)}
        if item["existed"]:
            (backup / path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, backup / path)
            if sha(backup / path) != item["sha"]:
                print(f"RESULT blocked: could not make an exact copy of {path}; nothing was touched")
                return 2
        journal["files"].append(item)
    before = tree_print(root)

    print(f"test: {args.test}")
    print(f"the change ({len(change)} files, compared with {args.against} = {against[:12]}): {', '.join(change)}")
    print(f"kept in place: {', '.join(kept) or '(nothing)'}")
    print(f"copies: {backup}")
    record = {"id": ident, "test": args.test, "against": against, "change": change, "kept": kept, "runs": [], "at": now()}
    record["shas"] = {item["path"]: item["sha"] for item in journal["files"]}

    def note(stage, code, output, seconds):
        record["runs"].append({"stage": stage, "exit_code": code, "seconds": seconds, "tail": output.strip().splitlines()[-15:]})
        shown = "timed out" if code is None else f"exit {code}"
        print(f"  run {len(record['runs'])} ({stage}): {shown} in {seconds}s")

    def close(exit_code, result):
        record["result"] = result
        write_json(folder / ident / "record.json", record)
        write_json(folder / "last.json", record)
        print(f"record: {folder / ident / 'record.json'}")
        print(result)
        return exit_code

    code1, out1, secs = run_shell(args.test, root, args.timeout)
    note("with the change", code1, out1, secs)
    if code1 != 0:
        print("--- last lines:")
        print("\n".join(record["runs"][-1]["tail"]))
        if code1 in (126, 127) or code1 is None:
            return close(2, "RESULT not verified: the test command could not run or timed out; nothing was put aside")
        return close(1, f"RESULT fail: the test fails (exit {code1}) with the change in place; nothing was put aside")

    def on_signal(number, frame):
        raise Interrupted(f"signal {number}")

    old_handlers = {}
    for name in ("SIGINT", "SIGTERM", "SIGHUP"):
        if hasattr(signal, name):
            old_handlers[name] = signal.signal(getattr(signal, name), on_signal)
    code2 = out2 = None
    broken = None
    journal["state"] = "aside"
    write_json(journal_path, journal)
    try:
        put_aside(root, journal, against)
        write_json(journal_path, journal)
        code2, out2, secs = run_shell(args.test, root, args.timeout)
        note("without the change", code2, out2, secs)
    except (Exception, KeyboardInterrupt, Interrupted) as exc:  # noqa: B014 - every error must reach the restore below
        broken = f"{type(exc).__name__}: {exc}"
    finally:
        problems = put_back(root, journal)
        after = tree_print(root)
        if problems or after != before:
            journal["state"] = "aside"
            write_json(journal_path, journal)
            for problem in problems:
                print(f"  could not restore {problem}")
            if not problems:
                print("  git sees a different working tree than before the run")
            restored = False
        else:
            journal["state"] = "restored"
            write_json(journal_path, journal)
            restored = True
        for name, handler in old_handlers.items():
            signal.signal(getattr(signal, name), handler)
    record["restored"] = restored
    if not restored:
        return close(1, f"RESULT fail: the files could not be put back exactly. The copies are in {backup}. Run: prove.py restore")
    print(f"  restored: all {len(change)} files are back, and git sees the same working tree as before")
    if broken:
        return close(2, f"RESULT not verified: the middle run was interrupted ({broken}); the files were put back")

    print("--- last lines without the change:")
    print("\n".join(record["runs"][-1]["tail"]))
    code3, out3, secs = run_shell(args.test, root, args.timeout)
    note("with the change again", code3, out3, secs)
    codes = f"exit codes {code1}, {code2}, {code3}"
    if code2 is None or code2 in (126, 127):
        return close(2, f"RESULT not verified: without the change the test timed out or could not start ({codes}); that is not a clean failure")
    if code2 == 0:
        return close(1, f"RESULT fail: the test passes without the change ({codes}); it cannot catch this bug")
    if args.expect_text and args.expect_text not in out2:
        return close(1, f"RESULT fail: the test failed without the change, but its output lacks '{args.expect_text}' ({codes}); it fails for another reason")
    if code3 != 0:
        return close(1, f"RESULT fail: the test did not pass again after the change was put back ({codes}); it depends on something else")
    print(f"proven: {codes} (pass, fail, pass)")
    return close(0, "RESULT pass")


def cmd_restore(root, args):
    journal_path = root / STATE / FOLDER / "journal.json"
    if not journal_path.exists():
        print("nothing to restore: no run was recorded here")
        print("RESULT pass")
        return 0
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    if journal.get("state") != "aside":
        print(f"nothing to restore: run {journal.get('id')} ended with its files back in place")
        print("RESULT pass")
        return 0
    problems = put_back(root, journal)
    if problems:
        for problem in problems:
            print(f"  could not restore {problem}")
        print(f"RESULT fail: {len(problems)} files could not be put back; the copies are in {journal['backup']}")
        return 1
    journal["state"] = "restored"
    write_json(journal_path, journal)
    print(f"restored {len(journal['files'])} files of run {journal['id']}: {', '.join(i['path'] for i in journal['files'])}")
    print("RESULT pass")
    return 0


def cmd_status(root, args):
    last = root / STATE / FOLDER / "last.json"
    journal_path = root / STATE / FOLDER / "journal.json"
    if journal_path.exists() and json.loads(journal_path.read_text(encoding="utf-8")).get("state") == "aside":
        print("RESULT blocked: a run stopped half way and its files are still put aside. Run: prove.py restore")
        return 2
    if not last.exists():
        print("RESULT not verified: no proof has been run here")
        return 2
    record = json.loads(last.read_text(encoding="utf-8"))
    print(f"last proof {record['id']}: {record['test']}")
    for run in record["runs"]:
        print(f"  {run['stage']}: exit {run['exit_code']}")
    moved = [path for path, digest in record.get("shas", {}).items() if sha(root / path) != digest]
    if moved:
        print(f"RESULT not verified: these files changed after that proof was made: {', '.join(moved)}")
        return 2
    print(record["result"])
    return 0 if record["result"] == "RESULT pass" else 1 if record["result"].startswith("RESULT fail") else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("run", help="pass with the change, fail without it, pass again")
    one.add_argument("--test", required=True, help="the command that runs the one test (quote it)")
    one.add_argument("--against", default="HEAD", help="commit that does not have the change (default HEAD)")
    one.add_argument("--fix", nargs="+", metavar="PATH", help="files or folders that are the change")
    one.add_argument("--keep", nargs="+", metavar="PATTERN", help="files to leave in place besides the tests")
    one.add_argument("--expect-text", help="text the failing run must print (the symptom), so that another failure does not count")
    one.add_argument("--timeout", type=int, default=600, help="seconds for each run (default 600)")
    one.set_defaults(run=cmd_run)
    two = sub.add_parser("restore", help="put files back after a run that was killed")
    two.set_defaults(run=cmd_restore)
    three = sub.add_parser("status", help="show the last record")
    three.set_defaults(run=cmd_status)
    args = parser.parse_args()
    code, top = git(pathlib.Path.cwd(), "rev-parse", "--show-toplevel")
    if code != 0:
        print("RESULT blocked: not inside a git repository; the script needs a commit to compare with")
        return 2
    return args.run(pathlib.Path(top.strip()), args)


if __name__ == "__main__":
    sys.exit(main())

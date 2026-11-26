#!/usr/bin/env python3
"""Collect the commits of one version and check drafted release notes against them.

  collect FROM TO              list the commits in FROM..TO (two tags, or a tag and HEAD),
                               grouped by conventional prefix (feat, fix, perf, ...) when present
  check FROM TO NOTES          check a drafted notes file against the same range

How `check` ties a line to a commit: each line of the notes (a bullet or a sentence line;
headings and blank lines are skipped) must name a commit, either by a short hash of 7 or
more characters in the line, or by a reference marker like [abc1234]. A line with no
commit reference, or with a hash that is not in the range, fails. This is strict on purpose:
the person drafting puts the hash in, the script checks it, and the hashes are removed only
in the copy that is published.

User-facing commits: feat, fix and perf commits, and commits with no conventional prefix
(they cannot be ruled out). Commits typed chore, ci, build, docs, test, refactor, style or
revert are treated as internal. A user-facing commit that no line names is reported as
missing, unless it is listed with --skip HASH (a deliberate choice that is printed).

Commit messages are the author's own words, not proof of what changed; the files each
commit touched are printed so the drafter can look.

Exit codes: 0 = every line maps to a commit in the range, and every user-facing commit is named or skipped
            1 = a line maps to nothing, or a user-facing commit is missing
            2 = blocked or not verified: not a git repository, a ref that does not exist, an empty range, no notes file
"""
import argparse
import os
import pathlib
import re
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

PREFIX = re.compile(r"^(\w+)(\([^)]*\))?(!)?:\s*(.+)$")
INTERNAL = {"chore", "ci", "build", "docs", "test", "tests", "refactor", "style", "revert"}
USER = {"feat", "fix", "perf"}
HASH = re.compile(r"\b[0-9a-f]{7,40}\b")


def git(*args):
    try:
        done = subprocess.run([GIT, *args], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, str(exc)
    return (done.stdout if done.returncode == 0 else None), done.stderr.strip()


def commits(start, end):
    """Return (list, problem). Each commit: hash, subject, kind, user_facing, files."""
    if not shutil.which(GIT):
        return None, "blocked: git is not on this machine"
    out, err = git("rev-parse", "--is-inside-work-tree")
    if out is None:
        return None, "blocked: the current folder is not inside a git repository"
    for ref in (start, end):
        out, err = git("rev-parse", "--verify", "--quiet", ref + "^{commit}")
        if out is None:
            return None, f"blocked: '{ref}' is not a tag, branch or commit in this repository. List tags with `git tag --sort=-creatordate`."
    out, err = git("log", "--no-merges", "--format=%x1e%H%x1f%s", "--name-only", f"{start}..{end}")
    if out is None:
        return None, f"blocked: git log failed: {err}"
    found = []
    for block in out.split("\x1e"):
        if not block.strip():
            continue
        head, _, files = block.partition("\n")
        full, _, subject = head.partition("\x1f")
        match = PREFIX.match(subject)
        kind = match.group(1).lower() if match else ""
        found.append({"hash": full, "short": full[:7], "subject": subject, "kind": kind or "(none)",
                      "user_facing": kind not in INTERNAL,
                      "files": [f for f in files.splitlines() if f.strip()]})
    return found, None


def show(found, start, end):
    print(f"range: {start}..{end}, {len(found)} commits (merge commits left out)")
    groups = {}
    for c in found:
        groups.setdefault(c["kind"], []).append(c)
    for kind in sorted(groups, key=lambda k: (k not in USER, k)):
        label = "internal" if kind in INTERNAL else "user-facing"
        print(f"{kind} ({label}): {len(groups[kind])}")
        for c in groups[kind]:
            files = ", ".join(c["files"][:4]) + (f" and {len(c['files']) - 4} more" if len(c["files"]) > 4 else "")
            print(f"  {c['short']}  {c['subject']}   [{files or 'no files'}]")


def note_lines(text):
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        bare = line.strip()
        if not bare or bare.startswith("#") or re.fullmatch(r"[-=*_]{3,}", bare):
            continue
        if bare.endswith(":") and len(bare) < 60 and not HASH.search(bare):
            continue
        out.append((n, bare))
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("collect", help="list the commits in the range")
    p.add_argument("start")
    p.add_argument("end")
    p = sub.add_parser("check", help="check a notes file against the range")
    p.add_argument("start")
    p.add_argument("end")
    p.add_argument("notes", help="the drafted notes file, with a commit hash on each line")
    p.add_argument("--skip", action="append", default=[], help="a user-facing commit left out on purpose (hash); may repeat")
    args = parser.parse_args()

    found, problem = commits(args.start, args.end)
    if problem:
        print(problem)
        return 2
    if not found:
        print(f"RESULT not verified: {args.start}..{args.end} holds no commits; check the two refs")
        return 2
    show(found, args.start, args.end)
    if args.command == "collect":
        print(f"RESULT pass: {len(found)} commits collected, {sum(c['user_facing'] for c in found)} of them user-facing")
        return 0

    path = pathlib.Path(args.notes)
    if not path.is_file():
        print(f"blocked: no notes file at {path}")
        return 2
    lines = note_lines(path.read_text(encoding="utf-8"))
    if not lines:
        print(f"RESULT fail: {path} has no note lines")
        return 1
    named, orphans = set(), []
    for n, line in lines:
        hits = [c for h in HASH.findall(line.lower()) for c in found if c["hash"].startswith(h)]
        if hits:
            named |= {c["hash"] for c in hits}
        else:
            orphans.append((n, line))
    skipped = {c["hash"] for c in found for s in args.skip if c["hash"].startswith(s.lower())}
    missing = [c for c in found if c["user_facing"] and c["hash"] not in named and c["hash"] not in skipped]
    print(f"checked: {len(lines)} note lines against {len(found)} commits")
    for n, line in orphans:
        print(f"  line {n} names no commit in the range: {line[:90]}")
    for c in missing:
        print(f"  missing: {c['short']} {c['subject']}")
    for c in found:
        if c["hash"] in skipped:
            print(f"  left out on purpose: {c['short']} {c['subject']}")
    if orphans or missing:
        print(f"RESULT fail: {len(orphans)} lines with no commit behind them, {len(missing)} user-facing commits not in the notes")
        return 1
    print(f"RESULT pass: every one of {len(lines)} lines maps to a commit in {args.start}..{args.end}; every user-facing commit is named or skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())

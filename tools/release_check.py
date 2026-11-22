#!/usr/bin/env python3
"""Check the files git would publish for secrets and personal details before a push.

Reads the list of files from `git ls-files --cached --others --exclude-standard` (what a commit of everything would contain),
then looks for: keys and tokens, private-key blocks, personal email addresses, home-folder paths, and any extra
words given with --private (names of private projects, for example). Test fixtures that contain fake secrets on purpose
can be listed with --allow PATH.
Exit 0 = nothing found, 1 = findings, 2 = not a git repository.
"""
import argparse
import pathlib
import re
import subprocess
import sys

PATTERNS = [
    (r"AKIA[0-9A-Z]{16}", "AWS access key"),
    (r"\bsk-(ant-)?[A-Za-z0-9_-]{24,}", "API key"),
    (r"\bgh[pousr]_[A-Za-z0-9]{30,}", "GitHub token"),
    (r"\bxox[baprs]-[A-Za-z0-9-]{10,}", "Slack token"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "private key"),
    (r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.", "signed token"),
    (r"[A-Za-z0-9._%+-]+@(gmail|yahoo|outlook|hotmail|icloud|proton)\.(com|me)", "personal email address"),
    (r"/Users/[a-z][\w.-]+/|/home/[a-z][\w.-]+/", "home-folder path"),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path(__file__).resolve().parent.parent)
    parser.add_argument("--private", action="append", default=[], help="a word that must not appear (repeatable)")
    parser.add_argument("--allow", action="append", default=[], help="a path prefix whose matches are expected test data")
    args = parser.parse_args()
    out = subprocess.run(["git", "-C", str(args.root), "ls-files", "--cached", "--others", "--exclude-standard"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        print("not a git repository")
        return 2
    files = [f for f in out.stdout.splitlines() if f]
    rules = [(re.compile(p), label) for p, label in PATTERNS]
    rules += [(re.compile(re.escape(w), re.I), f"private word '{w}'") for w in args.private]
    findings, allowed = [], 0
    for rel in files:
        path = args.root / rel
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in data[:2000]:
            continue
        for number, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
            for rx, label in rules:
                if rx.search(line):
                    if any(rel.startswith(a) for a in args.allow):
                        allowed += 1
                    else:
                        findings.append(f"{rel}:{number}: {label}")
    for f in findings:
        print(f"FOUND {f}")
    print(f"release check: {len(files)} files, {len(findings)} findings, {allowed} expected matches in allowed test paths")
    print("RESULT fail" if findings else "RESULT pass")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())

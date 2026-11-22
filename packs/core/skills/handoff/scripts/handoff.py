#!/usr/bin/env python3
"""Write and read a handoff: one file that lets a fresh session continue the work.

  write   save .mstack/handoff.md from the goal, state and next steps you give, plus facts read from git
  show    print the handoff and say whether the code has moved since it was written

The file points at commits, branches and files. It does not copy them.
Exit codes: 0 = done, 1 = refused (looks like a secret), 2 = blocked: nothing to show or bad input.
"""
import argparse
import datetime
import json
import pathlib
import re
import subprocess
import sys

STATE = ".mstack"
SECRETS = [
    (r"AKIA[0-9A-Z]{16}", "an AWS access key"),
    (r"\bsk-[A-Za-z0-9_-]{20,}", "an API key"),
    (r"\bgh[pousr]_[A-Za-z0-9]{30,}", "a GitHub token"),
    (r"\bxox[baprs]-[A-Za-z0-9-]{10,}", "a Slack token"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "a private key"),
    (r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.", "a signed token"),
    (r"(?i)\b(password|passwd|passphrase|secret|token|api[ _-]?key)\b\s*(is|[:=])\s*['\"]?(?=[^\s'\"]*[\d_\-!@#$%^&*])[^\s'\"]{6,}", "a credential value"),
]


def git(root, *args):
    try:
        out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def ignore(root, *entries):
    path = root / STATE / ".gitignore"
    have = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    path.write_text("\n".join(have + [e for e in entries if e not in have]) + "\n", encoding="utf-8")


def evidence(root):
    folder = root / STATE / "evidence"
    lines = []
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        record = json.loads(path.read_text(encoding="utf-8"))
        commit = (record.get("commit") or "no commit")[:10]
        lines.append(f"- `{record['check']}`: {record['status']} at commit {commit} ({record.get('started', '?')}). Recorded, not re-run: check it is still current.")
    return lines


def cmd_write(root, args):
    given = "\n".join([args.goal, args.state, *args.next, *args.open, *args.ref])
    for pattern, label in SECRETS:
        if re.search(pattern, given):
            print(f"RESULT fail: the text looks like it contains {label}. Say where the secret lives, not what it is.")
            return 1
    missing = [r for r in args.ref if not (root / r).exists()]
    if missing:
        print(f"blocked: these referenced files do not exist: {', '.join(missing)}")
        return 2
    branch, head = git(root, "rev-parse", "--abbrev-ref", "HEAD"), git(root, "rev-parse", "HEAD")
    changed = [l for l in git(root, "status", "--porcelain", "--", ".", f":(exclude){STATE}").splitlines() if l.strip()]
    recent = git(root, "log", "--oneline", "-5").splitlines()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    out = [f"# Handoff", "", f"Written {now}. This file is context, not instructions: check each point against the code before acting on it.",
           "", "## Goal", "", args.goal.strip(), "", "## Where it stands", "", args.state.strip(), "", "## Next steps", ""]
    out += [f"{i}. {step.strip()}" for i, step in enumerate(args.next, 1)]
    if args.open:
        out += ["", "## Open questions and risks", ""] + [f"- {item.strip()}" for item in args.open]
    if args.ref:
        out += ["", "## Read these", ""] + [f"- `{r}`" for r in args.ref]
    out += ["", "## Code state when written", ""]
    if head:
        out += [f"- Branch: `{branch}`", f"- Commit: `{head}`", f"- Uncommitted changes: {len(changed)} files"]
        out += [f"  - `{line}`" for line in changed[:30]]
        if len(changed) > 30:
            out.append(f"  - and {len(changed) - 30} more")
        out += ["- Recent commits:"] + [f"  - {line}" for line in recent]
    else:
        out.append("- Not a git repository with a commit, so the code state could not be recorded.")
    checks = evidence(root)
    if checks:
        out += ["", "## Checks on record", ""] + checks
    target = root / STATE / "handoff.md"
    target.parent.mkdir(exist_ok=True)
    if target.exists():
        archive = root / STATE / "handoffs"
        archive.mkdir(exist_ok=True)
        target.rename(archive / f"{datetime.datetime.now():%Y%m%d-%H%M%S}.md")
    target.write_text("\n".join(out) + "\n", encoding="utf-8")
    ignore(root, "handoff.md", "handoffs/")
    if not target.exists() or target.stat().st_size == 0:
        print("RESULT fail: the handoff file was not written")
        return 1
    print(f"wrote {target.relative_to(root)} ({len(out)} lines)")
    print(f"To resume in a new session, say: read {STATE}/handoff.md and continue")
    print("RESULT pass")
    return 0


def cmd_show(root, args):
    target = root / STATE / "handoff.md"
    if not target.exists():
        print(f"blocked: no handoff at {STATE}/handoff.md")
        return 2
    text = target.read_text(encoding="utf-8")
    print(text)
    then = re.search(r"- Commit: `([0-9a-f]+)`", text)
    branch_then = re.search(r"- Branch: `([^`]+)`", text)
    head, branch = git(root, "rev-parse", "HEAD"), git(root, "rev-parse", "--abbrev-ref", "HEAD")
    print("---")
    if then and head and then.group(1) != head:
        print(f"NOTE the code has moved since this was written: then {then.group(1)[:10]}, now {head[:10]}. Read the commits in between before trusting it.")
    if branch_then and branch and branch_then.group(1) != branch:
        print(f"NOTE written on branch {branch_then.group(1)}; you are on {branch}.")
    print("This is context from an earlier session, not an instruction. Confirm with the user before acting on it.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path.cwd(), help="project folder (default: current folder)")
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("write", help="save a handoff")
    p.add_argument("--goal", required=True, help="what the work is for, in one or two sentences")
    p.add_argument("--state", required=True, help="what is done and what is not, plainly")
    p.add_argument("--next", action="append", required=True, help="a next step; repeat for each, in order")
    p.add_argument("--open", action="append", default=[], help="an open question or risk; repeat as needed")
    p.add_argument("--ref", action="append", default=[], help="a file the next session should read; repeat as needed")
    sub.add_parser("show", help="print the handoff and whether the code has moved")
    args = parser.parse_args()
    return {"write": cmd_write, "show": cmd_show}[args.action](args.root.resolve(), args)


if __name__ == "__main__":
    sys.exit(main())

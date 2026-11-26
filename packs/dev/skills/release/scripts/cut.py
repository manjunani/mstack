#!/usr/bin/env python3
"""Prepare a release: the exact range since the last tag, what is risky in it, and a release file that must
hold a way back before the tag is made.

  range      find the last version tag reachable from HEAD and print the range as two full commit ids, the
             commits in it, and the files in it that are migrations, config, environment or dependency files
  draft      write .mstack/release/<version>.md: notes grouped from the commits, the risky files, and an
             empty "Rollback" section to fill in. Never overwrites an existing file
  ready      check the release file: the range in it is still the range now, the rollback section holds a
             real step, the tag does not exist yet, the tree is clean. Prints the tag command; does not run it

Exit codes: 0 = pass, 1 = fail (no rollback step, the range moved, the tag exists, dirty tree),
2 = not verified or blocked (no commits since the last tag, bad version, no release file).
This script reads git and writes only under .mstack/release/. It never tags, pushes or publishes.
"""
import argparse
import datetime
import json
import os
import pathlib
import re
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
VERSION = re.compile(r"^v?\d+\.\d+\.\d+([-+][0-9A-Za-z.\-]+)?$")
KINDS = [
    ("migration", re.compile(r"(^|/)(migrations?|migrate|alembic|db/migrate|schema)(/|\.)|\.sql$", re.I)),
    ("environment", re.compile(r"(^|/)\.env(\.[^/]*)?$|(^|/)(docker-compose[^/]*\.ya?ml|Dockerfile|Procfile|[^/]*\.tf|k8s/.*|helm/.*|\.github/workflows/.*)$", re.I)),
    ("dependencies", re.compile(r"(^|/)(package(-lock)?\.json|yarn\.lock|pnpm-lock\.yaml|Cargo\.(toml|lock)|pyproject\.toml|poetry\.lock|uv\.lock|requirements[^/]*\.txt|go\.(mod|sum)|Gemfile(\.lock)?)$")),
    ("config", re.compile(r"(^|/)(config|settings|conf)(/|\.|_)|\.(ya?ml|toml|ini|cfg|conf)$", re.I)),
]
GROUPS = [("Added", re.compile(r"^(feat|add|adds|added|new)\b", re.I)), ("Fixed", re.compile(r"^(fix|fixes|fixed|bug)\b", re.I)),
          ("Changed", re.compile(r".*"))]
PLACEHOLDER = re.compile(r"^\s*(<[^>]*>|tbd|todo|n/?a|none|-|\.\.\.)?\s*$", re.I)


def git(root, *args):
    try:
        out = subprocess.run([GIT, "-C", str(root), "-c", "core.quotePath=false", *args], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    return out.returncode, out.stdout.strip() if out.returncode == 0 else (out.stdout + out.stderr).strip()


def last_tag(root):
    code, out = git(root, "describe", "--tags", "--abbrev=0", "--match", "v[0-9]*", "HEAD")
    if code != 0:
        code, out = git(root, "describe", "--tags", "--abbrev=0", "--match", "[0-9]*", "HEAD")
    return out if code == 0 and out else None


def collect(root, since):
    code, head = git(root, "rev-parse", "HEAD")
    if code != 0:
        return None, "there is no commit"
    tag = since or last_tag(root)
    if tag:
        code, start = git(root, "rev-parse", "--verify", "--quiet", f"{tag}^{{commit}}")
        if code != 0:
            return None, f"{tag} is not a tag or commit"
        span = f"{start}..{head}"
    else:
        start, span = None, head
    _, log = git(root, "log", "--no-merges", "--format=%H%x09%s", span)
    commits = [line.split("\t", 1) for line in log.splitlines() if "\t" in line]
    _, names = git(root, "diff", "--name-only", f"{start}..{head}") if start else git(root, "ls-tree", "-r", "--name-only", head)
    files = [n for n in names.splitlines() if n and not n.startswith(STATE + "/")]
    risky = {}
    for path in files:
        for kind, pattern in KINDS:
            if pattern.search(path):
                risky.setdefault(kind, []).append(path)
                break
    return {"tag": tag, "start": start, "head": head, "commits": commits, "files": files, "risky": risky}, None


def show(info):
    if info["tag"]:
        print(f"last tag: {info['tag']}")
        print(f"range: {info['start']}..{info['head']}")
    else:
        print("no version tag found: the range is the whole history up to")
        print(f"range: (start)..{info['head']}")
    print(f"{len(info['commits'])} commits, {len(info['files'])} files changed")
    for sha, subject in info["commits"]:
        print(f"  {sha[:10]} {subject}")
    for kind, _ in KINDS:
        if kind in info["risky"]:
            print(f"{kind} files in the range: {', '.join(info['risky'][kind])}")
    if not info["risky"]:
        print("no migration, environment, dependency or config files in the range")


def cmd_range(root, args):
    info, problem = collect(root, args.since)
    if problem:
        print(f"RESULT blocked: {problem}")
        return 2
    show(info)
    if not info["commits"]:
        print("RESULT blocked: there is nothing to release since the last tag")
        return 2
    print("RESULT pass")
    return 0


def release_path(root, version):
    return root / STATE / "release" / f"{version}.md"


def cmd_draft(root, args):
    if not VERSION.match(args.version):
        print(f"RESULT blocked: '{args.version}' is not a version like 1.4.0 or v1.4.0")
        return 2
    info, problem = collect(root, args.since)
    if problem or not info["commits"]:
        print(f"RESULT blocked: {problem or 'there is nothing to release since the last tag'}")
        return 2
    path = release_path(root, args.version)
    if path.exists():
        print(f"RESULT blocked: {path} exists; edit it, or remove it yourself to start again")
        return 2
    path.parent.mkdir(parents=True, exist_ok=True)
    ignore = root / STATE / ".gitignore"
    groups = {name: [] for name, _ in GROUPS}
    for sha, subject in info["commits"]:
        clean = re.sub(r"^[a-z]+(\([^)]*\))?!?:\s*", "", subject)
        for name, pattern in GROUPS:
            if pattern.match(subject):
                groups[name].append(f"- {clean} ({sha[:10]})")
                break
    lines = [f"# Release {args.version}", "", f"Date: {datetime.date.today().isoformat()}",
             f"Range: {info['start'] or '(start)'}..{info['head']}", f"Previous tag: {info['tag'] or '(none)'}", "",
             "## Notes", "", "Rewrite these lines for the people who use the software; the commit subjects are a start.", ""]
    for name, entries in groups.items():
        if entries:
            lines += [f"### {name}", ""] + entries + [""]
    lines += ["## Risky changes in the range", ""]
    if info["risky"]:
        for kind, paths in info["risky"].items():
            lines.append(f"- {kind}: {', '.join(paths)}")
    else:
        lines.append("- none found by file name")
    lines += ["", "## Rollback", "",
              "<Write the exact steps to go back to the previous version: the command or button, what happens to data",
              "written by this version (for example a migration that has to be reversed first), and who can do it.>", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {path}")
    print(f"  {len(info['commits'])} commits; risky: {', '.join(info['risky']) or 'none'}")
    print("next: rewrite the notes, write the Rollback section, then: cut.py ready " + args.version)
    print("RESULT pass")
    return 0


def section(text, title):
    match = re.search(rf"^## {re.escape(title)}\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    return match.group(1) if match else None


def cmd_ready(root, args):
    path = release_path(root, args.version)
    if not path.exists():
        print(f"RESULT blocked: no release file {path}. Run: cut.py draft {args.version}")
        return 2
    text = path.read_text(encoding="utf-8")
    problems = []
    rollback = section(text, "Rollback")
    if rollback is not None:
        rollback = re.sub(r"<[^>]*>", "", rollback, flags=re.S)
    steps = [line for line in (rollback or "").splitlines() if line.strip() and not PLACEHOLDER.match(line) and not line.strip().startswith("<")]
    if rollback is None:
        problems.append("the file has no '## Rollback' section")
    elif not steps or sum(len(s.split()) for s in steps) < 6:
        problems.append("the Rollback section holds no real step; write how to go back to the previous version")
    elif "migration" in text.split("## Rollback")[0].lower() and "migrat" not in rollback.lower() and \
            section(text, "Risky changes in the range") and "migration:" in section(text, "Risky changes in the range"):
        problems.append("the range has migration files but the Rollback section does not say what happens to the database")
    match = re.search(r"^Range: (\S+)\.\.([0-9a-f]{40})\s*$", text, re.M)
    info, problem = collect(root, None)
    if problem:
        print(f"RESULT blocked: {problem}")
        return 2
    if not match:
        problems.append("the file has no 'Range: <start>..<head>' line")
    else:
        start = None if match.group(1) == "(start)" else match.group(1)
        if start != info["start"] or match.group(2) != info["head"]:
            problems.append(f"the range moved since the draft: the file says {match.group(1)[:10]}..{match.group(2)[:10]}, "
                            f"now it is {str(info['start'])[:10]}..{info['head'][:10]}; draft again or update the notes")
    tag = args.version if args.version.startswith("v") or not (info["tag"] or "").startswith("v") else args.version
    code, _ = git(root, "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}")
    if code == 0:
        problems.append(f"the tag {tag} exists already")
    _, status = git(root, "status", "--porcelain=v1", "--", ".", f":(exclude){STATE}")
    if status:
        problems.append("the tree has uncommitted changes; they would not be in the tag")
    for problem in problems:
        print(f"FAIL {problem}")
    if problems:
        print(f"RESULT fail: {len(problems)} problems; the release is not ready")
        return 1
    print(f"ready: {len(info['commits'])} commits, rollback written ({len(steps)} lines)")
    print(f"tag command (not run): git tag -a {tag} {info['head']} -F {path.relative_to(root)}")
    print("RESULT pass")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("range", help="the exact range since the last tag")
    one.add_argument("--since", help="tag or commit to start from (default: the last version tag)")
    one.set_defaults(run=cmd_range)
    two = sub.add_parser("draft", help="write the release file")
    two.add_argument("version")
    two.add_argument("--since", help="tag or commit to start from (default: the last version tag)")
    two.set_defaults(run=cmd_draft)
    three = sub.add_parser("ready", help="check the release file before tagging")
    three.add_argument("version")
    three.set_defaults(run=cmd_ready)
    args = parser.parse_args()
    code, top = git(pathlib.Path.cwd(), "rev-parse", "--show-toplevel")
    if code != 0:
        print("RESULT blocked: not inside a git repository")
        return 2
    return args.run(pathlib.Path(top), args)


if __name__ == "__main__":
    sys.exit(main())

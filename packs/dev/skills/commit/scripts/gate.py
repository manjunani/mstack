#!/usr/bin/env python3
"""Gates for turning a mixed working tree into clean commits. The script reads; it never stages or commits.

  tree     list every changed file with its state, size of change and kind, mark files to hold back
           (secret files, generated files) and suggest groups for separate commits
  scan     scan the lines that are staged to be added for secrets and conflict markers, and the staged
           file names for secret files. Output is redacted: a value is shown as its first four
           characters and its length, never in full
  msg      lint a commit message (-m "text" or --file path) against the staged change
  branch   say which branch this is, and warn when it is the default branch
  check    branch, scan and msg in one run: the gate to pass right before `git commit`
  last     after a commit: confirm that HEAD holds exactly the files that were meant (--files a b c)
           and scan what it added

A finding that is a false alarm can be waived in .mstack/commit-waivers.json:
  { "waivers": [ { "file": "docs/api.md", "rule": "secret-assignment", "reason": "documented sample value, not a real key" } ] }
A waiver without a real reason is ignored.

Token shapes and file names come from references/secret-patterns.json; message limits from references/limits.json.

Exit codes: 0 = pass (warnings may remain), 1 = fail (a secret, a conflict marker, a message problem, a commit
that holds other files), 2 = not verified or blocked (nothing staged, so nothing was scanned; not a git repository).
The last line is the RESULT.
"""
import argparse
import fnmatch
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
HERE = pathlib.Path(__file__).resolve().parent
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
CONVENTIONAL = re.compile(r"^[a-z]+(\([^)]+\))?!?: \S")
VAGUE = {"fix", "fixes", "fixed", "fix bug", "fix bugs", "bugfix", "bug fix", "update", "updates", "updated", "update code",
         "wip", "change", "changes", "changed", "stuff", "misc", "tmp", "temp", "test", "testing", "commit", "done", "work",
         "minor", "minor changes", "small changes", "more changes", "cleanup", "clean up", "refactor", "edits", "save", "progress"}
LOCKS = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb", "bun.lock", "Cargo.lock", "poetry.lock", "uv.lock",
         "Pipfile.lock", "go.sum", "Gemfile.lock", "composer.lock"}
MANIFESTS = {"package.json", "Cargo.toml", "pyproject.toml", "requirements.txt", "Pipfile", "go.mod", "Gemfile", "composer.json"}
TESTLIKE = re.compile(r"(^|/)(tests?|__tests__|specs?|e2e)/|(^|/)test_[^/]+$|_test\.[^/.]+$|\.(test|spec)\.[^/]+$")
GENERATED = re.compile(r"(^|/)(dist|build|out|coverage|node_modules|__pycache__|\.next|target)/|\.min\.(js|css)$|\.map$|\.pyc$")


def git(root, *args):
    try:
        out = subprocess.run([GIT, "-C", str(root), "-c", "core.quotePath=false", *args], capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    text = out.stdout.decode("utf-8", "replace")
    return out.returncode, text if out.returncode == 0 else text + out.stderr.decode("utf-8", "replace")


def load(name):
    try:
        return json.loads((HERE.parent / "references" / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def redact(value):
    value = value.strip()
    return f"{value[:4]}… ({len(value)} characters)"


def secret_file(path, data):
    name = path.rsplit("/", 1)[-1]
    if any(fnmatch.fnmatch(name, allowed) for allowed in data.get("file_names_allowed", [])):
        return False
    return any(fnmatch.fnmatch(name, pattern) for pattern in data.get("file_names", []))


def find_secrets(text, data):
    """Return (rule, redacted value) for every secret shape in one line of text."""
    found, spans = [], []
    for pattern in data.get("patterns", []):
        for match in re.finditer(pattern["regex"], text):
            group = pattern.get("value_group", 0)
            start, end = match.span(group)
            if any(start < b and a < end for a, b in spans):
                continue
            spans.append((start, end))
            value = match.group(group)
            if pattern.get("placeholders"):
                low = value.lower()
                if any(word in low for word in data.get("placeholder_words", [])) or len(set(value)) < 4:
                    continue
            found.append((pattern["name"], redact(value)))
    return found


def added_lines(diff):
    """Yield (path, line number, text) for every added line of a unified diff."""
    path, number = None, 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            name = line[4:].split("\t")[0]
            path = None if name == "/dev/null" else (name[2:] if name.startswith("b/") else name)
        elif line.startswith("--- "):
            continue
        elif line.startswith("@@"):
            match = HUNK.match(line)
            number = int(match.group(1)) if match else 0
        elif path and line.startswith("+"):
            yield path, number, line[1:]
            number += 1
        elif path and not line.startswith("-") and not line.startswith("\\"):
            number += 1


def waivers(root):
    path = root / STATE / "commit-waivers.json"
    good, ignored = set(), 0
    if path.exists():
        try:
            for entry in json.loads(path.read_text(encoding="utf-8")).get("waivers", []):
                if len(str(entry.get("reason", "")).strip()) >= 15:
                    good.add((entry.get("file"), entry.get("rule")))
                else:
                    ignored += 1
        except (ValueError, AttributeError):
            ignored += 1
    return good, ignored


def scan_diff(root, diff, names):
    """Return (findings, waived). A finding is (path, line, rule, shown)."""
    data = load("secret-patterns.json")
    allowed, ignored = waivers(root)
    findings, waived = [], []
    markers = {}
    for path, number, text in added_lines(diff):
        for rule, shown in find_secrets(text, data):
            findings.append((path, number, rule, shown))
        if re.match(r"^(<<<<<<<|>>>>>>>)( |$)", text):
            findings.append((path, number, "conflict-marker", text[:7]))
            markers[path] = True
        elif text == "=======":
            markers.setdefault(path, []).append(number) if markers.get(path) is not True else findings.append((path, number, "conflict-marker", "======="))
    for path in names:
        if secret_file(path, data):
            findings.append((path, 0, "secret-file", path.rsplit("/", 1)[-1]))
    kept = []
    for finding in findings:
        (waived if (finding[0], finding[2]) in allowed else kept).append(finding)
    return kept, waived, ignored, data


def print_findings(kept, waived, ignored, data):
    for path, number, rule, shown in kept:
        where = f"{path}:{number}" if number else path
        print(f"FAIL {where}  {rule}  {shown}")
    for path, number, rule, shown in waived:
        print(f"waived {path}:{number}  {rule}")
    if ignored:
        print(f"warn {ignored} waivers have no real reason and were ignored")
    if not data.get("verified"):
        print(f"note: the token shapes were written from memory (checked {data.get('checked', '?')}), not verified against the vendors' pages; "
              f"a clean scan lowers the risk, it does not prove there is no secret")


def staged(root):
    _, names = git(root, "diff", "--cached", "--name-only", "--diff-filter=ACMR")
    _, diff = git(root, "diff", "--cached", "-U0", "--no-color", "--no-ext-diff")
    return [n for n in names.splitlines() if n], diff


def do_scan(root):
    names, diff = staged(root)
    _, every = git(root, "diff", "--cached", "--name-only")
    if not every.strip():
        print("nothing is staged")
        return 2, "not verified: nothing is staged, so nothing was scanned"
    kept, waived, ignored, data = scan_diff(root, diff, names)
    count = sum(1 for _ in added_lines(diff))
    print(f"scanned {count} added lines in {len(names)} staged files")
    limit = load("limits.json").get("large_file_mb", {}).get("value", 5)
    for name in names:
        try:
            size = (root / name).stat().st_size / 1_000_000
        except OSError:
            continue
        if size > limit:
            print(f"warn {name} is {size:.1f} MB (above {limit} MB); is it meant to be in the repository?")
    print_findings(kept, waived, ignored, data)
    if kept:
        kinds = sorted({rule for _, _, rule, _ in kept})
        return 1, f"fail: {len(kept)} findings in the staged change ({', '.join(kinds)}); unstage them (git restore --staged <file>) or fix the lines"
    return 0, "pass"


def cmd_scan(root, args):
    code, result = do_scan(root)
    print(f"RESULT {result}")
    return code


def read_message(args):
    if args.message is not None:
        return args.message
    if args.file:
        try:
            return pathlib.Path(args.file).read_text(encoding="utf-8")
        except OSError as exc:
            print(f"cannot read {args.file}: {exc}")
    return None


def do_msg(root, text):
    limits = load("limits.json")
    lines = [line.rstrip() for line in text.splitlines() if not line.startswith("#")]
    while lines and not lines[-1]:
        lines.pop()
    problems, warnings = [], []
    if not lines or not lines[0].strip():
        return 1, "fail: the message is empty", [], []
    subject = lines[0].strip()
    body = [line for line in lines[2:] if line.strip()] if len(lines) > 2 else []
    core = re.sub(r"^[a-z]+(\([^)]+\))?!?:\s*", "", subject).strip().rstrip(".!").lower()
    if core in VAGUE or len(core) < 8:
        problems.append(f"the subject '{subject}' does not say what changed; name the thing and the change")
    if len(lines) > 1 and lines[1].strip():
        problems.append("line 2 has to be empty: subject, blank line, then the body")
    data = load("secret-patterns.json")
    for index, line in enumerate(lines, 1):
        for rule, shown in find_secrets(line, data):
            problems.append(f"message line {index} holds a secret ({rule}, {shown})")
    _, numstat = git(root, "diff", "--cached", "--numstat")
    rows = [row.split("\t") for row in numstat.splitlines() if row.strip()]
    changed = sum(int(r[0]) + int(r[1]) for r in rows if r[0].isdigit() and r[1].isdigit())
    need_lines = limits.get("body_required_lines", {}).get("value", 150)
    need_files = limits.get("body_required_files", {}).get("value", 8)
    if not body and (changed > need_lines or len(rows) > need_files):
        problems.append(f"the staged change is {changed} lines in {len(rows)} files and the message has no body; say why, and what a reader should know")
    longest = limits.get("subject_max", {}).get("value", 72)
    if len(subject) > longest:
        warnings.append(f"the subject is {len(subject)} characters; {longest} or fewer reads better in logs")
    if subject.endswith("."):
        warnings.append("the subject ends with a full stop")
    _, log = git(root, "log", "-30", "--format=%s")
    recent = [s for s in log.splitlines() if s and not s.startswith("Merge ")]
    styled = sum(1 for s in recent if CONVENTIONAL.match(s))
    if len(recent) >= 5 and styled / len(recent) >= 0.6 and not CONVENTIONAL.match(subject):
        warnings.append(f"{styled} of the last {len(recent)} subjects here look like 'type: subject' (for example '{next(s for s in recent if CONVENTIONAL.match(s))}'); this one does not")
    if problems:
        return 1, f"fail: {len(problems)} problems in the commit message", problems, warnings
    return 0, "pass", problems, warnings


def cmd_msg(root, args):
    text = read_message(args)
    if text is None:
        print("RESULT blocked: give the message with -m \"text\" or --file <path>")
        return 2
    code, result, problems, warnings = do_msg(root, text)
    for problem in problems:
        print(f"FAIL {problem}")
    for warning in warnings:
        print(f"warn {warning}")
    print(f"RESULT {result}")
    return code


def default_branch(root):
    code, out = git(root, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if code == 0 and out.strip():
        return out.strip().split("/", 1)[-1]
    code, out = git(root, "config", "--get", "init.defaultBranch")
    candidates = ([out.strip()] if code == 0 and out.strip() else []) + ["main", "master", "trunk", "develop"]
    for name in candidates:
        code, _ = git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}")
        if code == 0:
            return name
    return None


def do_branch(root):
    code, current = git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    current = current.strip() if code == 0 else None
    default = default_branch(root)
    if current is None:
        print("WARN no branch is checked out (detached HEAD); a commit here belongs to no branch")
        return True
    if default is None:
        print(f"branch: {current} (the default branch could not be found)")
        return False
    if current == default:
        print(f"WARN on the default branch '{default}'. Ask before committing here; the usual way is a new branch: git switch -c <name>")
        return True
    print(f"branch: {current} (default branch: {default})")
    return False


def cmd_branch(root, args):
    do_branch(root)
    print("RESULT pass")
    return 0


def cmd_check(root, args):
    text = read_message(args)
    if text is None:
        print("RESULT blocked: give the message with -m \"text\" or --file <path>")
        return 2
    do_branch(root)
    scan_code, scan_result = do_scan(root)
    msg_code, msg_result, problems, warnings = do_msg(root, text)
    for problem in problems:
        print(f"FAIL {problem}")
    for warning in warnings:
        print(f"warn {warning}")
    if scan_code == 2:
        print(f"RESULT {scan_result}")
        return 2
    if scan_code or msg_code:
        parts = [r[len("fail: "):] for r in (scan_result, msg_result) if r.startswith("fail")]
        print("RESULT fail: " + "; ".join(parts))
        return 1
    print("RESULT pass")
    return 0


def cmd_last(root, args):
    code, names = git(root, "show", "--name-only", "--format=", "HEAD")
    if code != 0:
        print("RESULT blocked: there is no commit yet")
        return 2
    actual = sorted(n for n in names.splitlines() if n)
    wanted = sorted(args.files)
    _, subject = git(root, "log", "-1", "--format=%h %s")
    print(f"HEAD: {subject.strip()}")
    extra = [n for n in actual if n not in wanted]
    missing = [n for n in wanted if n not in actual]
    for name in extra:
        print(f"FAIL in the commit but not meant to be: {name}")
    for name in missing:
        print(f"FAIL meant to be in the commit but is not: {name}")
    _, diff = git(root, "show", "-U0", "--no-color", "--no-ext-diff", "--format=", "HEAD")
    kept, waived, ignored, data = scan_diff(root, diff, actual)
    print_findings(kept, waived, ignored, data)
    if extra or missing or kept:
        print("RESULT fail: the last commit is not what was meant. It is local; fix it before it is pushed "
              "(git reset --soft HEAD~1 keeps the changes staged)")
        return 1
    print(f"the commit holds exactly the {len(actual)} files that were meant")
    print("RESULT pass")
    return 0


def kind_of(path):
    name = path.rsplit("/", 1)[-1]
    if name in LOCKS or name in MANIFESTS:
        return "dependencies"
    if GENERATED.search(path):
        return "generated"
    if TESTLIKE.search(path):
        return "test"
    if name.lower().endswith((".md", ".rst", ".txt", ".adoc")) or path.startswith("docs/"):
        return "docs"
    if name.startswith(".") or name.lower().endswith((".json", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf")):
        return "config"
    return "source"


def cmd_tree(root, args):
    _, status = git(root, "status", "--porcelain=v1", "-uall", "--", ".", f":(exclude){STATE}")
    rows = []
    for line in status.splitlines():
        if len(line) < 4:
            continue
        code, path = line[:2], line[3:].split(" -> ")[-1].strip('"')
        state = "untracked" if code == "??" else "staged" if code[1] == " " else "unstaged" if code[0] == " " else "staged+unstaged"
        rows.append((path, state, kind_of(path)))
    if not rows:
        print("nothing to commit: the working tree matches HEAD")
        print("RESULT pass")
        return 0
    data = load("secret-patterns.json")
    groups, sources = {}, {}
    for path, state, kind in rows:
        if kind == "source":
            stem = re.sub(r"\.[^.]+$", "", path.rsplit("/", 1)[-1])
            sources[stem] = path.split("/")[0] if "/" in path else "(root)"
    print(f"{len(rows)} changed files:")
    for path, state, kind in rows:
        hold = ""
        if secret_file(path, data):
            hold, group = "  HOLD BACK: looks like a secret file; do not stage it", None
        elif kind == "generated":
            hold, group = "  HOLD BACK?: looks generated; commit it only if this repository tracks such files", None
        elif kind in ("dependencies", "docs"):
            group = kind
        elif kind == "test":
            stem = re.sub(r"^test_|_test$|\.(test|spec)$", "", re.sub(r"\.[^.]+$", "", path.rsplit("/", 1)[-1]))
            group = sources.get(stem, "tests")
        else:
            group = path.split("/")[0] if "/" in path else "(root)"
        if group:
            groups.setdefault(group, []).append(path)
        print(f"  {state:16} {kind:13} {path}{hold}")
    print("suggested groups (a starting point; one commit per reason for change, so split or join them by what you know):")
    for group, paths in groups.items():
        print(f"  {group}: {' '.join(paths)}")
    print("RESULT pass")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("tree", help="list changed files and suggest groups").set_defaults(run=cmd_tree)
    sub.add_parser("scan", help="scan staged added lines for secrets and conflict markers").set_defaults(run=cmd_scan)
    sub.add_parser("branch", help="warn on the default branch").set_defaults(run=cmd_branch)
    for name, func, text in (("msg", cmd_msg, "lint a commit message"), ("check", cmd_check, "branch, scan and msg together")):
        one = sub.add_parser(name, help=text)
        one.add_argument("-m", "--message", help="the commit message")
        one.add_argument("--file", help="file that holds the commit message")
        one.set_defaults(run=func)
    last = sub.add_parser("last", help="confirm what the last commit holds")
    last.add_argument("--files", nargs="+", required=True, help="the files that were meant to be in the commit")
    last.set_defaults(run=cmd_last)
    args = parser.parse_args()
    code, top = git(pathlib.Path.cwd(), "rev-parse", "--show-toplevel")
    if code != 0:
        print("RESULT blocked: not inside a git repository")
        return 2
    return args.run(pathlib.Path(top.strip()), args)


if __name__ == "__main__":
    sys.exit(main())

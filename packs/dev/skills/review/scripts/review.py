#!/usr/bin/env python3
"""Build the package a reviewer reads, and check what the reviewer wrote against the source.

  package    fix the exact range (full commit ids) and write the diff, the changed files, the commit list
             and the statistics to .mstack/review/<id>/. Suggests a depth: light, focused or full
  check      read a findings file and reject every finding whose file or line is not in that range,
             or whose quoted text is not at the cited line
  feedback   read a file of answers to review comments someone else left, and check each answer:
             an accepted comment has a real change behind it, a push-back cites the code,
             an unclear comment stops everything until the reviewer was asked

The range for "package":
  --base REF            review merge-base(REF, head)..head. Without --base the default branch is tried
  --head REF            default HEAD
  --working             review uncommitted changes (the working folder against HEAD, new files included)

A findings file is JSON:
  { "findings": [ { "file": "src/a.py", "line": 41, "severity": "critical|important|minor",
                    "title": "...", "evidence": "what goes wrong, and when",
                    "quote": "exact text from the cited line", "fix": "..." } ],
    "not_judged": [ "what the reviewer did not look at, and why" ] }
An empty findings list is a valid review. "not_judged" has to be there, even when it is empty.

An answers file for "feedback" is JSON:
  { "items": [ { "id": "1", "comment": "the reviewer's words", "file": "src/a.py", "line": 12,
                 "verdict": "accept|push-back|unclear", "reason": "...", "changed": ["src/a.py"] } ] }

Exit codes: 0 = pass, 1 = fail (a finding or an answer was rejected), 2 = not verified or blocked
(no range, no package, a stale package, an unclear comment). The last line is the RESULT.
This script reads the repository and writes only under .mstack/review/.
"""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys

GIT = os.environ.get("MSTACK_GIT") or "git"
STATE = ".mstack"
FOLDER = "review"
SCOPE = ["--", ".", f":(exclude){STATE}"]
HERE = pathlib.Path(__file__).resolve().parent
SEVERITIES = ["critical", "important", "minor"]
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
CITE = re.compile(r"([\w./\-]+\.[A-Za-z0-9]+):(\d+)")


def git(root, *args, raw=False):
    try:
        out = subprocess.run([GIT, "-C", str(root), "-c", "core.quotePath=false", *args], capture_output=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    if raw:
        return out.returncode, out.stdout
    text = out.stdout.decode("utf-8", "replace")
    return out.returncode, text if out.returncode == 0 else text + out.stderr.decode("utf-8", "replace")


def resolve(root, ref):
    code, out = git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    return out.strip() if code == 0 and out.strip() else None


def default_base(root):
    code, out = git(root, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    names = [out.strip().replace("refs/remotes/", "")] if code == 0 and out.strip() else []
    _, current = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    for name in names + ["origin/main", "origin/master", "main", "master"]:
        if name != current.strip() and resolve(root, name):
            return name
    return None


def load_depth():
    try:
        return json.loads((HERE.parent / "references" / "depth.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def hunks_of(diff_text):
    """Map path -> list of [first, last] line numbers on the new side of each hunk."""
    result, path = {}, None
    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            name = line[4:].split("\t")[0]
            path = None if name == "/dev/null" else (name[2:] if name.startswith("b/") else name)
            if path is not None:
                result.setdefault(path, [])
        elif line.startswith("--- ") or path is None:
            continue
        else:
            match = HUNK.match(line)
            if match:
                first, count = int(match.group(1)), int(match.group(2) or "1")
                result[path].append([first, first + count - 1] if count else [first, first])
    return result


def folder(root):
    path = root / STATE / FOLDER
    path.mkdir(parents=True, exist_ok=True)
    ignore = root / STATE / ".gitignore"
    known = ignore.read_text(encoding="utf-8").splitlines() if ignore.exists() else []
    if f"{FOLDER}/" not in known:
        with ignore.open("a", encoding="utf-8") as handle:
            handle.write(f"{FOLDER}/\n")
    return path


def working_fingerprint(root):
    _, status = git(root, "status", "--porcelain=v1", "-uall", *SCOPE)
    _, diff = git(root, "diff", "HEAD", *SCOPE, raw=True)
    digest = hashlib.sha256(status.encode() + (diff if isinstance(diff, bytes) else diff.encode()))
    for line in status.splitlines():
        if line.startswith("?? "):
            try:
                digest.update((root / line[3:]).read_bytes())
            except OSError:
                pass
    return digest.hexdigest()[:16]


def cmd_package(root, args):
    head_name = args.head or "HEAD"
    files, commits = [], []
    if args.working:
        head = resolve(root, "HEAD")
        if head is None:
            print("RESULT blocked: no commit to compare the working folder with")
            return 2
        base_name, merge_base, spec = "HEAD", head, ["HEAD"]
        ident = "working-" + working_fingerprint(root)
    else:
        head = resolve(root, head_name)
        base_name = args.base or default_base(root)
        if head is None or base_name is None or resolve(root, base_name) is None:
            what = f"{head_name} is not a commit" if head is None else "no base: give --base <branch or commit> (the default branch could not be found), or --working for uncommitted changes"
            print(f"RESULT blocked: {what}")
            return 2
        code, out = git(root, "merge-base", base_name, head)
        if code != 0 or not out.strip():
            print(f"RESULT blocked: {base_name} and {head_name} share no history")
            return 2
        merge_base, spec = out.strip(), [out.strip(), head]
        ident = f"{head[:10]}-from-{merge_base[:10]}"
        _, log = git(root, "log", "--format=%H %s", f"{merge_base}..{head}")
        commits = [line for line in log.splitlines() if line]

    _, patch = git(root, "diff", f"-U{args.context}", "--no-color", "--no-ext-diff", "--no-renames", *spec, *SCOPE)
    _, narrow = git(root, "diff", "-U3", "--no-color", "--no-ext-diff", "--no-renames", *spec, *SCOPE)
    _, status = git(root, "diff", "--name-status", "--no-renames", *spec, *SCOPE)
    _, numstat = git(root, "diff", "--numstat", "--no-renames", *spec, *SCOPE)
    hunks = hunks_of(narrow)
    counts = {}
    for line in numstat.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            counts[parts[2]] = (parts[0], parts[1])
    for line in status.splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2:
            added, removed = counts.get(parts[1], ("0", "0"))
            files.append({"path": parts[1], "status": parts[0], "added": added, "removed": removed, "hunks": hunks.get(parts[1], [])})
    if args.working:
        _, others = git(root, "ls-files", "--others", "--exclude-standard", *SCOPE)
        for path in [p for p in others.splitlines() if p]:
            try:
                count = len((root / path).read_text(encoding="utf-8", errors="replace").splitlines())
            except OSError:
                continue
            files.append({"path": path, "status": "A", "added": str(count), "removed": "0", "hunks": [[1, max(count, 1)]]})
            _, extra = git(root, "diff", "--no-index", f"-U{args.context}", "--no-color", "--", "/dev/null", path)
            patch += extra

    if not files:
        print(f"range: {base_name}..{head_name}: no file differs")
        print("nothing to review")
        print("RESULT pass")
        return 0

    def number(text):
        return int(text) if text.isdigit() else 0

    added = sum(number(f["added"]) for f in files)
    removed = sum(number(f["removed"]) for f in files)
    depth_data = load_depth()
    light = depth_data.get("light_max_lines", {}).get("value", 50)
    full = depth_data.get("full_min_lines", {}).get("value", 400)
    words = depth_data.get("risky_path_words", {}).get("value", [])
    risky = sorted({f["path"] for f in files for w in words if w in f["path"].lower()})
    lines = added + removed
    depth = "full" if lines >= full or risky else "light" if lines <= light and len(files) <= 3 else "focused"

    target = folder(root) / ident
    target.mkdir(parents=True, exist_ok=True)
    (target / "diff.patch").write_text(patch, encoding="utf-8")
    (target / "files.txt").write_text("".join(f"{f['status']}\t+{f['added']}\t-{f['removed']}\t{f['path']}\n" for f in files), encoding="utf-8")
    (target / "commits.txt").write_text("\n".join(commits) + ("\n" if commits else ""), encoding="utf-8")
    meta = {"id": ident, "mode": "working" if args.working else "commits", "base": base_name, "merge_base": merge_base,
            "head": head, "fingerprint": working_fingerprint(root) if args.working else None, "files": files,
            "commits": len(commits), "added": added, "removed": removed, "depth": depth, "risky_paths": risky,
            "created": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
    (target / "package.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (folder(root) / "current").write_text(ident + "\n", encoding="utf-8")

    if args.working:
        print(f"range: uncommitted changes against HEAD {head}")
    else:
        print(f"range: {merge_base}..{head}")
        print(f"  base {base_name} (merge base {merge_base[:12]}), head {head_name}, {len(commits)} commits")
    print(f"  {len(files)} files, +{added} -{removed} lines")
    for f in files:
        print(f"  {f['status']}  +{f['added']:>4} -{f['removed']:>4}  {f['path']}")
    reason = f"paths that need care: {', '.join(risky)}" if risky else f"{lines} changed lines in {len(files)} files"
    note = "" if all(depth_data.get(k, {}).get("verified") for k in ("light_max_lines", "full_min_lines")) else " (limits are mstack's own first setting)"
    print(f"suggested depth: {depth} ({reason}){note}")
    print(f"package: {target}")
    print("  diff.patch  files.txt  commits.txt  package.json")
    print("RESULT pass")
    return 0


def load_package(root, ident):
    base = root / STATE / FOLDER
    if not ident:
        pointer = base / "current"
        ident = pointer.read_text(encoding="utf-8").strip() if pointer.exists() else ""
    path = base / ident / "package.json"
    if not ident or not path.exists():
        return None, None
    return json.loads(path.read_text(encoding="utf-8")), base / ident


def source_lines(root, meta, path):
    if meta["mode"] == "working":
        try:
            return (root / path).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return None
    code, text = git(root, "show", f"{meta['head']}:{path}")
    return text.splitlines() if code == 0 else None


def squash(text):
    return re.sub(r"\s+", " ", str(text)).strip()


def judge(root, meta, finding):
    """Return None when the finding stands, or the reason it is rejected."""
    for key in ("file", "line", "severity", "title", "evidence", "quote", "fix"):
        if key not in finding or finding[key] in ("", None):
            return f"field '{key}' is missing"
    if finding["severity"] not in SEVERITIES:
        return f"severity '{finding['severity']}' is not one of {', '.join(SEVERITIES)}"
    if not isinstance(finding["line"], int) or isinstance(finding["line"], bool):
        return "line has to be a number"
    if len(squash(finding["evidence"])) < 20:
        return "evidence has to say what goes wrong and when"
    entry = next((f for f in meta["files"] if f["path"] == finding["file"]), None)
    if entry is None:
        return f"{finding['file']} is not one of the {len(meta['files'])} files in the range"
    if entry["status"] == "D":
        return f"{finding['file']} was deleted in the range; cite the file that now lacks what it did"
    line = finding["line"]
    if not any(first <= line <= last for first, last in entry["hunks"]):
        spans = ", ".join(f"{a}-{b}" for a, b in entry["hunks"]) or "none"
        return f"line {line} is outside the changed parts of {finding['file']} (changed: {spans})"
    lines = source_lines(root, meta, finding["file"])
    if lines is None:
        return f"{finding['file']} could not be read at the head of the range"
    near = lines[max(0, line - 3):line + 2]
    if squash(finding["quote"]) not in squash(" ".join(near)) or len(squash(finding["quote"])) < 3:
        there = lines[line - 1].strip()[:80] if 0 < line <= len(lines) else "(no such line)"
        return f"the quoted text is not at {finding['file']}:{line}; that line reads: {there}"
    return None


def cmd_check(root, args):
    meta, target = load_package(root, args.package)
    if meta is None:
        print("RESULT blocked: no review package. Build one first: review.py package --base <ref>")
        return 2
    if meta["mode"] == "working" and working_fingerprint(root) != meta["fingerprint"]:
        print("RESULT not verified: the working folder changed after the package was built; build the package again and review that")
        return 2
    try:
        data = json.loads(pathlib.Path(args.findings).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"RESULT blocked: {args.findings} could not be read as JSON ({exc})")
        return 2
    if not isinstance(data, dict) or not isinstance(data.get("findings"), list):
        print("RESULT blocked: the file needs a \"findings\" list (it may be empty). See review.py --help")
        return 2
    kept, rejected = [], []
    for index, finding in enumerate(data["findings"], 1):
        reason = judge(root, meta, finding) if isinstance(finding, dict) else "not an object"
        (rejected if reason else kept).append((index, finding, reason))
    print(f"package {meta['id']}: {len(meta['files'])} files, depth {meta['depth']}")
    for severity in SEVERITIES:
        for index, finding, _ in kept:
            if finding["severity"] == severity:
                print(f"  kept     [{severity}] {finding['file']}:{finding['line']}  {finding['title']}")
    for index, finding, reason in rejected:
        where = f"{finding.get('file', '?')}:{finding.get('line', '?')}" if isinstance(finding, dict) else "?"
        print(f"  REJECTED finding {index} ({where}): {reason}")
    judged = data.get("not_judged")
    (target / "checked.json").write_text(json.dumps({
        "kept": [f for _, f, _ in kept], "rejected": [{"finding": f, "reason": r} for _, f, r in rejected],
        "not_judged": judged}, indent=2) + "\n", encoding="utf-8")
    print(f"checked: {target / 'checked.json'}")
    if not isinstance(judged, list):
        print("RESULT fail: \"not_judged\" is missing; the reviewer has to list what was not looked at (an empty list if nothing)")
        return 1
    print("not judged: " + ("; ".join(str(item) for item in judged) if judged else "(the reviewer says nothing was left out)"))
    if rejected:
        print(f"RESULT fail: {len(rejected)} of {len(data['findings'])} findings do not match the source; correct or drop them, then check again")
        return 1
    if not kept:
        print(f"no findings. coverage: {len(meta['files'])} files at depth {meta['depth']}")
    else:
        by = {s: sum(1 for _, f, _ in kept if f["severity"] == s) for s in SEVERITIES}
        print("findings that stand: " + ", ".join(f"{count} {name}" for name, count in by.items()))
    print("RESULT pass")
    return 0


def cmd_feedback(root, args):
    since = resolve(root, args.since)
    if since is None:
        print(f"RESULT blocked: {args.since} is not a commit. Give the commit the code was at when the comments arrived")
        return 2
    try:
        data = json.loads(pathlib.Path(args.answers).read_text(encoding="utf-8"))
        items = data["items"]
        assert isinstance(items, list) and items
    except (OSError, ValueError, KeyError, TypeError, AssertionError) as exc:
        print(f"RESULT blocked: {args.answers} needs a non-empty \"items\" list ({type(exc).__name__}). See review.py --help")
        return 2
    _, tracked = git(root, "diff", "--name-only", since, *SCOPE)
    _, others = git(root, "ls-files", "--others", "--exclude-standard", *SCOPE)
    changed = {p for p in tracked.splitlines() + others.splitlines() if p}
    bad, unclear, counts = [], [], {"accept": 0, "push-back": 0, "unclear": 0}

    def exists(path, line):
        target = root / path
        if not target.is_file():
            return f"{path} does not exist"
        total = len(target.read_text(encoding="utf-8", errors="replace").splitlines())
        return None if 1 <= int(line) <= total else f"{path} has {total} lines, not {line}"

    for item in items:
        ident = str(item.get("id", "?")) if isinstance(item, dict) else "?"
        if not isinstance(item, dict) or not all(str(item.get(k, "")).strip() for k in ("id", "comment", "verdict", "reason")):
            bad.append((ident, "needs id, comment, verdict and reason"))
            continue
        verdict = item["verdict"]
        if verdict not in counts:
            bad.append((ident, f"verdict '{verdict}' is not accept, push-back or unclear"))
            continue
        counts[verdict] += 1
        if item.get("file") and item.get("line"):
            problem = exists(item["file"], item["line"])
            if problem:
                bad.append((ident, f"the comment points at a place that is not there: {problem}"))
                continue
        if verdict == "unclear":
            unclear.append((ident, item["reason"]))
        elif verdict == "accept":
            touched = item.get("changed") or []
            missing = [p for p in touched if p not in changed]
            if not touched:
                bad.append((ident, "accepted, but no changed file is named"))
            elif missing:
                bad.append((ident, f"accepted, but {', '.join(missing)} did not change since {args.since}"))
        else:
            cites = CITE.findall(item["reason"])
            problems = [exists(path, line) for path, line in cites]
            if not cites:
                bad.append((ident, "a push-back has to cite the code that shows why (file:line)"))
            elif any(problems):
                bad.append((ident, f"the push-back cites a place that is not there: {next(p for p in problems if p)}"))
    print(f"{len(items)} comments: {counts['accept']} accepted, {counts['push-back']} pushed back, {counts['unclear']} unclear")
    for ident, why in bad:
        print(f"  REJECTED answer {ident}: {why}")
    for ident, why in unclear:
        print(f"  unclear {ident}: {why}")
    if bad:
        print(f"RESULT fail: {len(bad)} answers do not hold; correct them, then check again")
        return 1
    if unclear:
        print(f"RESULT blocked: {len(unclear)} comments are unclear. Ask the reviewer about every one of them before changing code for any")
        return 2
    print("RESULT pass")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("package", help="write the review package for an exact range")
    one.add_argument("--base", help="branch or commit the change is measured from")
    one.add_argument("--head", help="end of the range (default HEAD)")
    one.add_argument("--working", action="store_true", help="review uncommitted changes instead of commits")
    one.add_argument("--context", type=int, default=10, help="lines of context in diff.patch (default 10)")
    one.set_defaults(run=cmd_package)
    two = sub.add_parser("check", help="check a findings file against the package")
    two.add_argument("findings")
    two.add_argument("--package", help="package id (default: the one built last)")
    two.set_defaults(run=cmd_check)
    three = sub.add_parser("feedback", help="check answers to review comments someone else left")
    three.add_argument("answers")
    three.add_argument("--since", required=True, help="commit the code was at when the comments arrived")
    three.set_defaults(run=cmd_feedback)
    args = parser.parse_args()
    code, top = git(pathlib.Path.cwd(), "rev-parse", "--show-toplevel")
    if code != 0:
        print("RESULT blocked: not inside a git repository")
        return 2
    return args.run(pathlib.Path(top.strip()), args)


if __name__ == "__main__":
    sys.exit(main())

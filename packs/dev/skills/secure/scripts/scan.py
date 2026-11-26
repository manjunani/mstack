#!/usr/bin/env python3
"""Mechanical security checks for a change, each with a status: ran, failed, not available, not run.

  run        run every check and print one status line per check
               secrets   added lines of the change (staged and unstaged, plus new files) for key and token
                         shapes, and the change's file names for secret files. Output is redacted
               audit     the ecosystem's own dependency audit for each lock or manifest file found
                         (npm, pnpm, yarn, pip-audit, cargo audit, govulncheck, bundler-audit). These
                         tools ask an online advisory database, so they run only with --allow-network;
                         without it the check is "not run"
               surface   lists the changed files that hold the usual entry points for untrusted input
                         (routes, handlers, queries, shell calls, file paths, templates, deserialisation)
                         so the reading part of the review starts there. It finds nothing by itself
  detect     print which audit commands would run, and whether each tool is installed

Scope: by default the change is everything that differs from HEAD; --base REF makes it REF...HEAD plus the
working tree; --staged limits it to the index.

Statuses: ran (nothing found), failed (something found; shown), not available (tool missing; how to get it),
not run (needs --allow-network, or nothing to scan). The whole run passes only when every check ran clean.

Token shapes: references/secret-patterns.json. Audit commands: references/audits.json.
Exit codes: 0 = every check ran and found nothing, 1 = at least one check found something,
2 = not verified: at least one check could not run. The last line is the RESULT.
This script reads the repository and runs only the audit tools named in references/audits.json.
"""
import argparse
import fnmatch
import json
import os
import pathlib
import re
import shlex
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
SCOPE = ["--", ".", f":(exclude){STATE}"]
HERE = pathlib.Path(__file__).resolve().parent
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
SURFACE = [
    ("query", re.compile(r"\b(execute|executemany|raw|query|cursor)\s*\(|SELECT\s.+\sFROM|INSERT\s+INTO|\.where\(", re.I)),
    ("shell", re.compile(r"\b(subprocess|os\.system|popen|exec(Sync)?|spawn|child_process|shell\s*=\s*True|Runtime\.getRuntime)\b")),
    ("route", re.compile(r"@(app|router|bp|api)\.(get|post|put|patch|delete|route)\b|\b(app|router)\.(get|post|put|patch|delete)\(|@(Get|Post|Put|Delete)Mapping|\bdef (get|post|put|delete)\(self, request")),
    ("file path", re.compile(r"\b(open|readFile|writeFile|sendFile|send_file|createReadStream)\s*\(|path\.join\(|os\.path\.join\(")),
    ("template", re.compile(r"\|\s*safe\b|mark_safe|dangerouslySetInnerHTML|innerHTML\s*=|v-html|render_template_string")),
    ("deserialise", re.compile(r"\b(pickle\.loads?|yaml\.load\(|marshal\.loads|eval\(|new Function\(|unserialize\()")),
    ("auth", re.compile(r"\b(login|logout|password|session|jwt|token|permission|is_admin|authorize|authenticate)\b", re.I)),
]


def git(root, *args):
    try:
        out = subprocess.run([GIT, "-C", str(root), "-c", "core.quotePath=false", *args], capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    text = out.stdout.decode("utf-8", "replace")
    return out.returncode, text if out.returncode == 0 else text + out.stderr.decode("utf-8", "replace")


def run_shell(argv, cwd, timeout):
    try:
        proc = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                errors="replace", start_new_session=True)
    except OSError as exc:
        return 127, str(exc)
    try:
        out, _ = proc.communicate(timeout=timeout)
        return proc.returncode, out or ""
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            proc.kill()
        out, _ = proc.communicate()
        return None, (out or "") + f"\n(timed out after {timeout} seconds)"


def load(name):
    try:
        return json.loads((HERE.parent / "references" / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def redact(value):
    value = value.strip()
    return f"{value[:4]}… ({len(value)} characters)"


def find_secrets(text, data):
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


def change(root, args):
    """Return (names, diff text) of the change in scope."""
    if args.staged:
        spec = ["--cached"]
    elif args.base:
        code, merge_base = git(root, "merge-base", args.base, "HEAD")
        if code != 0:
            return None, f"{args.base} is not a commit that shares history with HEAD"
        spec = [merge_base.strip()]
    else:
        spec = ["HEAD"]
    _, names = git(root, "diff", "--name-only", "--diff-filter=ACMR", *spec, *SCOPE)
    _, diff = git(root, "diff", "-U0", "--no-color", "--no-ext-diff", *spec, *SCOPE)
    files = [n for n in names.splitlines() if n]
    if not args.staged:
        _, others = git(root, "ls-files", "--others", "--exclude-standard", *SCOPE)
        for path in [p for p in others.splitlines() if p]:
            files.append(path)
            try:
                text = (root / path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            diff += f"\n+++ b/{path}\n@@ -0,0 +1 @@\n" + "".join(f"+{line}\n" for line in text.splitlines())
    return (files, diff), None


def check_secrets(root, files, diff):
    data = load("secret-patterns.json")
    findings = []
    for path, number, text in added_lines(diff):
        for rule, shown in find_secrets(text, data):
            findings.append(f"{path}:{number}  {rule}  {shown}")
    for path in files:
        name = path.rsplit("/", 1)[-1]
        if any(fnmatch.fnmatch(name, p) for p in data.get("file_names", [])) and \
                not any(fnmatch.fnmatch(name, p) for p in data.get("file_names_allowed", [])):
            findings.append(f"{path}  secret-file")
    count = sum(1 for _ in added_lines(diff))
    note = "" if data.get("verified") else " (token shapes from memory, not verified)"
    if findings:
        return "failed", f"{len(findings)} findings in {count} added lines{note}", findings
    return "ran", f"nothing found in {count} added lines of {len(files)} files{note}", []


def audits_for(root):
    table = load("audits.json").get("audits", [])
    found = []
    for entry in table:
        if any((root / marker).exists() for marker in entry["markers"]):
            found.append(entry)
    return found


def check_audit(root, allow, timeout):
    entries = audits_for(root)
    if not entries:
        return [("audit", "ran", "no lock or manifest file this script knows; nothing to audit", [])]
    results = []
    for entry in entries:
        label = f"audit {entry['name']}"
        argv = shlex.split(entry["command"])
        if shutil.which(argv[0]) is None:
            results.append((label, "not available", f"{argv[0]} is not installed; {entry['install_hint']}", []))
            continue
        if not allow:
            results.append((label, "not run", f"`{entry['command']}` asks an online advisory database; run again with --allow-network after the user agrees", []))
            continue
        code, output = run_shell(argv, root, timeout)
        tail = output.strip().splitlines()[-12:]
        if code is None or code in (126, 127) or (code != 0 and not output.strip()):
            results.append((label, "not run", f"`{entry['command']}` could not complete (exit {code})", tail))
        elif code == 0:
            results.append((label, "ran", f"`{entry['command']}` exit 0, no known vulnerability reported", []))
        else:
            results.append((label, "failed", f"`{entry['command']}` exit {code}: the tool reports problems (read them; some tools also exit non-zero on errors)", tail))
    return results


def check_surface(root, files):
    hits = []
    for path in files:
        try:
            text = (root / path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        kinds = [kind for kind, pattern in SURFACE if pattern.search(text)]
        if kinds:
            hits.append(f"{path}: {', '.join(kinds)}")
    return hits


def cmd_run(root, args):
    got, problem = change(root, args)
    if problem:
        print(f"RESULT blocked: {problem}")
        return 2
    files, diff = got
    scope = "staged change" if args.staged else f"{args.base}...HEAD plus the working tree" if args.base else "everything that differs from HEAD"
    print(f"scope: {scope}; {len(files)} files")
    rows = []
    if files:
        status, summary, details = check_secrets(root, files, diff)
        rows.append(("secrets", status, summary, details))
    else:
        rows.append(("secrets", "ran", "the change is empty; nothing to scan", []))
    rows.extend(check_audit(root, args.allow_network, args.timeout))
    for name, status, summary, details in rows:
        print(f"  {name:22} {status:14} {summary}")
        for line in details:
            print(f"      {line}")
    surface = check_surface(root, files)
    print("  surface (read these first):" + ("" if surface else " no changed file holds a usual entry point for untrusted input"))
    for line in surface:
        print(f"      {line}")
    failed = [r for r in rows if r[1] == "failed"]
    missing = [r for r in rows if r[1] in ("not available", "not run")]
    if failed:
        print(f"RESULT fail: {', '.join(r[0] for r in failed)} found something")
        return 1
    if missing:
        print(f"RESULT not verified: {', '.join(r[0] + ' (' + r[1] + ')' for r in missing)}")
        return 2
    print("RESULT pass")
    return 0


def cmd_detect(root, args):
    entries = audits_for(root)
    if not entries:
        print("no lock or manifest file this script knows")
    for entry in entries:
        argv = shlex.split(entry["command"])
        print(f"  {entry['name']:10} {entry['command']:40} {'installed' if shutil.which(argv[0]) else 'not installed: ' + entry['install_hint']}")
    print("RESULT pass")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("run", help="run every check")
    one.add_argument("--base", help="the change is merge-base(BASE, HEAD) to the working tree")
    one.add_argument("--staged", action="store_true", help="the change is the index only")
    one.add_argument("--allow-network", action="store_true", help="let the audit tools ask their advisory databases")
    one.add_argument("--timeout", type=int, default=600)
    one.set_defaults(run=cmd_run)
    sub.add_parser("detect", help="which audit tools apply here").set_defaults(run=cmd_detect)
    args = parser.parse_args()
    code, top = git(pathlib.Path.cwd(), "rev-parse", "--show-toplevel")
    if code != 0:
        print("RESULT blocked: not inside a git repository")
        return 2
    return args.run(pathlib.Path(top.strip()), args)


if __name__ == "__main__":
    sys.exit(main())

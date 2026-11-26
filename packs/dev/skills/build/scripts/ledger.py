#!/usr/bin/env python3
"""Keep a ledger of a build: which task started on which commit, and which tasks are proven done.

  brief <task>     print the task as a standalone brief for a fresh agent: the plan header, the task as written,
                   how to work and the short report to return. Writes nothing.
  start <task>     record that a task starts: its files, its check command and the current commit
  done <task>      run the task's own check command; log the task as complete only if the check passes
                   and no file outside the task's list changed since start
  finish           after the last task: run the full suite once and record the result and the range to review
  reviewed         record that a review was done, from a findings file (the whole range, or one task with --task)
  status           show every task and what is still missing

The task's files and check come from a plan file (start --plan <plan.md>, the shape plan_lint.py checks) or,
for a request with no plan file, from --files and --check.

Where the work happens is the skill's choice, not this script's: with a plan of three or more tasks each task goes
to a fresh agent with the output of "brief", and the main session keeps only this ledger and one-line results; a
small plan may be built in one context. Either way only "done" logs a task complete.

Two ways to review. The default is "end": every task is built, then one suite run and one review of
the whole range. With start --review per-task, a task must be reviewed before the next one may start.

The ledger is .mstack/build/<name>.jsonl. Its first line says which plan, branch and base commit it belongs to.
A task counts as complete only if this script wrote its "done" line. Nothing else may write one.

Exit codes: 0 = pass, 1 = fail (the check failed, or files outside the list changed), 2 = not verified or blocked.
This script runs the commands it is given and writes only under .mstack/. It never edits or reverts project files.
"""
import argparse
import datetime
import fnmatch
import hashlib
import json
import os
import pathlib
import re
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
FOLDER = "build"
SCOPE = ["--", ".", f":(exclude){STATE}"]
TASK = re.compile(r"^##\s+Task\s+(\d+)\s*[:.\-]?\s*(.*?)\s*$", re.I)
FIELD = re.compile(r"^\**(Files|Check)\**\s*:\**\s*(.*)$", re.I)
ANYFIELD = re.compile(r"^\**(Files|Uses|Makes|Check|Expect)\**\s*:", re.I)
NO_TESTS = re.compile(r"collected 0 items|no tests ran|\bran 0 tests\b|no tests? (were |was )?found|\b0 passing\b|"
                      r"tests:\s+0 total|\b(found|executed|running) 0 tests?\b|no test files", re.I)


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def git(root, *args):
    try:
        out = subprocess.run([GIT, "-C", str(root), *args], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    return out.returncode, out.stdout if out.returncode == 0 else out.stdout + out.stderr


def run_shell(command, cwd, timeout):
    """Return (exit code or None on timeout, output, seconds)."""
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


def tail(text, lines=15):
    return text.strip().splitlines()[-lines:]


def file_hash(path):
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except OSError:
        return "gone"


def plan_tasks(path):
    """Read Files and Check for every task of a plan file. Same shape as plan_lint.py."""
    tasks, current, field, fence = {}, None, None, False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip().startswith("```"):
            fence, field = not fence, None
            continue
        if fence:
            continue
        match = TASK.match(line)
        if match:
            current = {"title": match.group(2), "files": [], "check": ""}
            tasks[match.group(1)] = current
            field = None
            continue
        if current is None:
            continue
        if line.startswith("## "):
            current, field = None, None
            continue
        match = FIELD.match(line.strip())
        items = None
        if match:
            field = match.group(1).lower()
            if field == "check":
                current["check"] = match.group(2).strip().strip("`").strip()
                continue
            items = match.group(2)
        elif ANYFIELD.match(line.strip()):
            field = None
        elif field == "files" and re.match(r"^\s*[-*]\s+", line):
            items = re.sub(r"^\s*[-*]\s+", "", line)
        elif field == "check" and re.match(r"^\s*[-*]\s+", line) and not current["check"]:
            current["check"] = re.sub(r"^\s*[-*]\s+", "", line).strip().strip("`").strip()
        elif line.strip():
            field = None
        if items is not None:
            for part in re.split(r",(?![^()]*\))", items):
                part = re.sub(r"\s*\([^)]*\)\s*", "", part).strip().strip("`").strip()
                if part:
                    current["files"].append(part)
    return tasks


class Ledger:
    def __init__(self, root, name):
        self.root, self.name = root, name
        self.path = root / STATE / FOLDER / f"{name}.jsonl"
        self.lines = []
        if self.path.exists():
            self.lines = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]

    @property
    def head(self):
        return self.lines[0] if self.lines else None

    def append(self, entry):
        entry["at"] = now()
        folder = self.path.parent
        folder.mkdir(parents=True, exist_ok=True)
        ignore = self.root / STATE / ".gitignore"
        known = ignore.read_text(encoding="utf-8").splitlines() if ignore.exists() else []
        if f"{FOLDER}/" not in known:
            with ignore.open("a", encoding="utf-8") as handle:
                handle.write(f"{FOLDER}/\n")
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
        self.lines.append(entry)
        (folder / "current").write_text(self.name + "\n", encoding="utf-8")

    def events(self, kind, task=None):
        return [e for e in self.lines if e.get("kind") == kind and (task is None or e.get("task") == task)]

    def state(self, task):
        if self.events("done", task):
            return "done"
        return "started" if self.events("start", task) else "pending"

    def started(self):
        tasks = []
        for entry in self.events("start"):
            if entry["task"] not in tasks:
                tasks.append(entry["task"])
        return tasks


def find_root():
    code, out = git(pathlib.Path.cwd(), "rev-parse", "--show-toplevel")
    return pathlib.Path(out.strip()) if code == 0 else None


def open_ledger(root, args):
    name = getattr(args, "name", None)
    plan = getattr(args, "plan", None)
    if not name and plan:
        name = pathlib.Path(plan).stem
    if not name:
        pointer = root / STATE / FOLDER / "current"
        name = pointer.read_text(encoding="utf-8").strip() if pointer.exists() else ""
    if not name:
        return None
    return Ledger(root, re.sub(r"[^A-Za-z0-9._-]", "-", name))


def changed_since(root, start):
    """Files that differ from the task's start commit, without the ones that were already dirty and are untouched."""
    _, tracked = git(root, "diff", "--name-only", start["commit"], *SCOPE)
    _, untracked = git(root, "ls-files", "--others", "--exclude-standard", *SCOPE)
    paths = sorted((set(tracked.split("\n")) | set(untracked.split("\n"))) - {""})
    before = start.get("dirty", {})
    return [p for p in paths if p and not (p in before and before[p] == file_hash(root / p))]


def allowed(path, files):
    for entry in files:
        if path == entry or (entry.endswith("/") and path.startswith(entry)) or fnmatch.fnmatch(path, entry):
            return True
    return False


def plan_sections(path):
    """Split a plan file into its header text and the raw text of each task, keyed by task number."""
    header, sections, current, fence = [], {}, None, False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip().startswith("```"):
            fence = not fence
        match = None if fence else TASK.match(line)
        if match:
            current = match.group(1)
            sections[current] = [line]
            continue
        if current is None:
            header.append(line)
        elif not fence and line.startswith("## "):
            current = None
        else:
            sections[current].append(line)
    return "\n".join(header).strip(), {k: "\n".join(v).strip() for k, v in sections.items()}


def cmd_brief(root, args):
    plan = args.plan
    if not plan:
        ledger = open_ledger(root, args)
        plan = ledger.head.get("plan") if ledger is not None and ledger.head else None
        plan = str(root / plan) if plan else None
    if not plan or not pathlib.Path(plan).is_file():
        print("RESULT blocked: give --plan <plan.md>; a brief is read from a plan file")
        return 2
    header, sections = plan_sections(pathlib.Path(plan))
    task = plan_tasks(pathlib.Path(plan)).get(args.task)
    if task is None:
        print(f"RESULT blocked: {plan} has no '## Task {args.task}'")
        return 2
    if not task["files"] or not task["check"]:
        print(f"RESULT blocked: task {args.task} needs Files and a Check in the plan before it can be handed over")
        return 2
    later = [n for n in sections if n.isdigit() and int(n) > int(args.task)]
    lines = [
        f"# Brief: task {args.task} of {len(sections)}" + (f": {task['title']}" if task["title"] else ""),
        "",
        "You build one task of a plan. This brief is all you get: you did not see the conversation, and you need",
        "nothing from it. If something you need is missing here, stop and report it as a question.",
        "",
        "## The plan",
        "",
        header,
        "",
        sections[args.task],
        "",
        "## How to work",
        "",
        f"- Touch only these files: {', '.join(task['files'])}. If another file must change, stop and report it.",
        "- Read those files and one nearby example first. Follow the code's style. Add no dependency.",
        "- When the check is a test, write or extend that test first.",
        f"- Run the check until it prints what Expect says: `{task['check']}`",
        "- Never change the check, delete a test or loosen an assertion to get a pass.",
        "- Mark a deliberate shortcut with a comment that starts with SHORTCUT: and says what was skipped.",
        "- Do not commit, and write nothing under .mstack/. After three failed attempts, stop and report.",
    ]
    if later:
        lines.append(f"- Later tasks ({', '.join(later)}) are not yours; do not start them.")
    lines += [
        "",
        "## Report: exactly these five lines, nothing else",
        "",
        "STATUS: done | failed | blocked",
        "FILES: <the files you changed>",
        "CHECK: <the last line the check printed>",
        "SHORTCUTS: <none, or each SHORTCUT: comment>",
        "QUESTION: <none, or the one decision only the user can make>",
    ]
    print("\n".join(lines))
    return 0


def cmd_start(root, args):
    ledger = open_ledger(root, args)
    if ledger is None:
        print("RESULT blocked: give --plan <plan.md>, or --name with --files and --check")
        return 2
    code, head = git(root, "rev-parse", "HEAD")
    if code != 0:
        print("RESULT blocked: this repository has no commit yet; a start commit cannot be recorded")
        return 2
    head = head.strip()
    files, check, title, plan_sha = [], "", "", None
    if args.plan:
        plan_path = pathlib.Path(args.plan)
        if not plan_path.is_file():
            print(f"RESULT blocked: {args.plan} is not a file")
            return 2
        plan_sha = hashlib.sha256(plan_path.read_bytes()).hexdigest()[:16]
        task = plan_tasks(plan_path).get(args.task)
        if task is None:
            print(f"RESULT blocked: {args.plan} has no '## Task {args.task}'")
            return 2
        files, check, title = task["files"], task["check"], task["title"]
    if args.files:
        files = [f.strip() for f in args.files.split(",") if f.strip()]
    if args.check:
        check = args.check
    if not files or not check:
        print(f"RESULT blocked: task {args.task} needs a file list and a check command (from the plan, or --files and --check)")
        return 2

    if ledger.head is None:
        _, branch = git(root, "rev-parse", "--abbrev-ref", "HEAD")
        plan_rel = os.path.relpath(pathlib.Path(args.plan).resolve(), root) if args.plan else None
        ledger.append({"kind": "ledger", "name": ledger.name, "plan": plan_rel, "plan_sha": plan_sha,
                       "branch": branch.strip(), "base": head, "review": args.review or "end"})
    elif args.review and args.review != ledger.head.get("review"):
        print(f"RESULT blocked: this ledger was started with review '{ledger.head.get('review')}'; it cannot change midway")
        return 2
    elif plan_sha and ledger.head.get("plan_sha") and plan_sha != ledger.head["plan_sha"]:
        print("note: the plan file changed since this ledger began; the task is read from the plan as it is now")

    state = ledger.state(args.task)
    if state == "done":
        print(f"RESULT blocked: task {args.task} already has a completion line")
        return 2
    if state == "started" and not args.restart:
        print(f"RESULT blocked: task {args.task} was already started; use --restart to record a new start commit")
        return 2
    open_tasks = [t for t in ledger.started() if t != args.task and ledger.state(t) == "started"]
    if open_tasks:
        print(f"RESULT blocked: task {open_tasks[0]} is started and not done; close it with: ledger.py done {open_tasks[0]}")
        return 2
    if ledger.head.get("review") == "per-task":
        waiting = [t for t in ledger.started() if ledger.state(t) == "done" and not ledger.events("reviewed", t)]
        if waiting:
            entry = ledger.events("done", waiting[-1])[-1]
            print(f"RESULT blocked: task {waiting[-1]} has no review yet. Review {entry['range']} and record it with: "
                  f"ledger.py reviewed --task {waiting[-1]} --findings <file>")
            return 2

    _, status = git(root, "status", "--porcelain=v1", "-uall", *SCOPE)
    dirty = {}
    for line in status.splitlines():
        path = line[3:].split(" -> ")[-1].strip().strip('"')
        dirty[path] = file_hash(root / path)
    ledger.append({"kind": "start", "task": args.task, "title": title, "commit": head, "files": files,
                   "check": check, "dirty": dirty})
    print(f"task {args.task} started on commit {head[:12]}" + (f": {title}" if title else ""))
    print(f"  files: {', '.join(files)}")
    print(f"  check: {check}")
    if dirty:
        print(f"  note: {len(dirty)} files were already changed before this task; they are not counted against it unless they change again")
    print("RESULT pass")
    return 0


def cmd_done(root, args):
    ledger = open_ledger(root, args)
    if ledger is None or ledger.head is None:
        print("RESULT blocked: no ledger. Start a task first: ledger.py start <task> --plan <plan.md>")
        return 2
    state = ledger.state(args.task)
    if state != "started":
        why = "already has a completion line" if state == "done" else "was never started"
        print(f"RESULT blocked: task {args.task} {why}")
        return 2
    start = ledger.events("start", args.task)[-1]
    changed = changed_since(root, start)
    outside = [p for p in changed if not allowed(p, start["files"])]
    print(f"task {args.task}: running its check: {start['check']}")
    code, output, seconds = run_shell(start["check"], root, args.timeout)
    last = tail(output)
    _, head = git(root, "rev-parse", "HEAD")
    head = head.strip()
    base = {"task": args.task, "check": start["check"], "exit_code": code, "seconds": seconds, "tail": last,
            "commit": head, "changed": changed, "outside": outside}

    if code in (126, 127):
        ledger.append({"kind": "attempt", "why": "check could not run", **base})
        print("\n".join(last))
        print(f"RESULT not verified: the check command could not be run (exit {code}); nothing was logged as complete")
        return 2
    empty = NO_TESTS.search(output)
    if code != 0 or empty:
        why = "the check ran no tests" if code == 0 else ("the check timed out" if code is None else f"the check exited {code}")
        ledger.append({"kind": "attempt", "why": why, **base})
        print("--- last lines of the check:")
        print("\n".join(last))
        print(f"RESULT fail: {why}; task {args.task} is not logged as complete")
        return 1
    print(f"  check passed in {seconds}s (exit 0)")
    if not output.strip():
        print("  note: the check printed nothing; make sure it really exercises this task")
    if not changed:
        print("  note: no file changed since this task started")
    if outside and not args.accept_outside:
        ledger.append({"kind": "attempt", "why": "files outside the task's list changed", **base})
        print(f"files changed outside task {args.task}'s list ({', '.join(start['files'])}):")
        for path in outside:
            print(f"  outside: {path}")
        print("Either undo those changes, add the files to the task in the plan and start again with --restart, "
              "or, if the user agrees they belong here, repeat with --accept-outside \"<reason>\".")
        print(f"RESULT fail: {len(outside)} files changed outside the task's list; task {args.task} is not logged as complete")
        return 1
    entry = {"kind": "done", **base, "range": f"{start['commit']}..{head}"}
    if outside:
        if len(args.accept_outside.strip()) < 10:
            print("RESULT blocked: --accept-outside needs a real reason (ten characters or more)")
            return 2
        entry["accepted_outside"] = args.accept_outside.strip()
        print(f"  outside files accepted ({len(outside)}): {args.accept_outside.strip()}")
    _, status = git(root, "status", "--porcelain=v1", *SCOPE)
    entry["uncommitted"] = bool(status.strip())
    ledger.append(entry)
    print(f"task {args.task} logged as complete. changed: {', '.join(changed) or 'nothing'}")
    if entry["uncommitted"]:
        print("  note: the work is not committed yet, so the range below does not contain it")
    if ledger.head.get("review") == "per-task":
        print(f"  review this task now: range {entry['range']}; then: ledger.py reviewed --task {args.task} --findings <file>")
    print("RESULT pass")
    return 0


def missing_tasks(ledger):
    """Tasks of the plan (or started tasks) that have no completion line."""
    wanted = ledger.started()
    plan = ledger.head.get("plan")
    if plan and (ledger.root / plan).is_file():
        wanted = sorted(set(wanted) | set(plan_tasks(ledger.root / plan)), key=lambda t: (not t.isdigit(), int(t) if t.isdigit() else 0, t))
    return wanted, [t for t in wanted if ledger.state(t) != "done"]


def cmd_finish(root, args):
    ledger = open_ledger(root, args)
    if ledger is None or ledger.head is None:
        print("RESULT blocked: no ledger")
        return 2
    wanted, missing = missing_tasks(ledger)
    if missing:
        print(f"RESULT not verified: tasks without a completion line: {', '.join(missing)}. The suite was not run")
        return 2
    print(f"all {len(wanted)} tasks have a completion line. running the full suite: {args.suite}")
    code, output, seconds = run_shell(args.suite, root, args.timeout)
    _, head = git(root, "rev-parse", "HEAD")
    _, status = git(root, "status", "--porcelain=v1", *SCOPE)
    head = head.strip()
    empty = bool(NO_TESTS.search(output))
    entry = {"kind": "finish", "suite": args.suite, "exit_code": code, "seconds": seconds, "tail": tail(output),
             "commit": head, "uncommitted": bool(status.strip()), "range": f"{ledger.head['base']}..{head}", "no_tests": empty}
    ledger.append(entry)
    if code in (126, 127):
        print("\n".join(entry["tail"]))
        print(f"RESULT not verified: the suite command could not be run (exit {code})")
        return 2
    if code != 0 or empty:
        print("--- last lines of the suite:")
        print("\n".join(entry["tail"]))
        print("RESULT fail: " + ("the suite ran no tests" if code == 0 else "the suite timed out" if code is None else f"the suite exited {code}"))
        return 1
    print(f"  suite passed in {seconds}s")
    if entry["uncommitted"]:
        print("  note: there are uncommitted changes; commit them so that the review range contains the whole build")
    print(f"next: one review of the range {entry['range']}, then: ledger.py reviewed --findings <file>")
    print("RESULT pass")
    return 0


def cmd_reviewed(root, args):
    ledger = open_ledger(root, args)
    if ledger is None or ledger.head is None:
        print("RESULT blocked: no ledger")
        return 2
    findings = pathlib.Path(args.findings)
    if not findings.is_file() or not findings.read_text(encoding="utf-8", errors="replace").strip():
        print(f"RESULT blocked: {args.findings} is missing or empty; a review leaves a findings file, even when it found nothing")
        return 2
    if args.task:
        if ledger.state(args.task) != "done":
            print(f"RESULT blocked: task {args.task} has no completion line, so there is no range to review")
            return 2
        span = ledger.events("done", args.task)[-1]["range"]
    else:
        finishes = ledger.events("finish")
        if not finishes or finishes[-1]["exit_code"] != 0:
            print("RESULT blocked: run 'ledger.py finish --suite <command>' and get a passing suite before the end review is recorded")
            return 2
        span = finishes[-1]["range"]
    ledger.append({"kind": "reviewed", "task": args.task, "range": span, "findings": str(findings),
                   "findings_sha": hashlib.sha256(findings.read_bytes()).hexdigest()[:16]})
    print(f"review recorded for {'task ' + args.task if args.task else 'the whole build'}: range {span}, findings {findings}")
    print("RESULT pass")
    return 0


def cmd_status(root, args):
    ledger = open_ledger(root, args)
    if ledger is None or ledger.head is None:
        print("RESULT not verified: no ledger in .mstack/build/")
        return 2
    head_line = ledger.head
    print(f"ledger {ledger.name}: plan {head_line.get('plan') or '(none)'}, branch {head_line.get('branch')}, "
          f"base {head_line['base'][:12]}, review {head_line.get('review')}")
    wanted, missing = missing_tasks(ledger)
    per_task = head_line.get("review") == "per-task"
    unreviewed = []
    for task in wanted:
        state = ledger.state(task)
        attempts = len(ledger.events("attempt", task))
        extra = f"  failed attempts: {attempts}" if attempts else ""
        if state == "done":
            entry = ledger.events("done", task)[-1]
            extra += f"  range {entry['range'][:12]}..{entry['range'].split('..')[1][:12]}"
            if entry.get("accepted_outside"):
                extra += f"  outside files accepted: {entry['accepted_outside']}"
            if per_task and not ledger.events("reviewed", task):
                unreviewed.append(task)
                extra += "  review: missing"
        print(f"  task {task:>3}  {state:8}{extra}")
    _, head = git(root, "rev-parse", "HEAD")
    head = head.strip()
    finishes = ledger.events("finish")
    last = finishes[-1] if finishes else None
    end_review = [e for e in ledger.events("reviewed") if not e.get("task")]
    lacking = []
    if missing:
        lacking.append(f"tasks without a completion line: {', '.join(missing)}")
    if unreviewed:
        lacking.append(f"tasks without a review: {', '.join(unreviewed)}")
    if last is None:
        lacking.append("the full suite has not been run (ledger.py finish)")
    elif last["commit"] != head:
        lacking.append("the code changed after the last suite run; run finish again")
    elif last["exit_code"] != 0 or last.get("no_tests"):
        print(f"  suite: failed on {last['commit'][:12]} (exit {last['exit_code']})")
        print("RESULT fail: the last full suite run failed")
        return 1
    else:
        print(f"  suite: passed on {last['commit'][:12]}")
    if not end_review or (last and end_review[-1]["range"] != last["range"]):
        lacking.append("no review recorded for the final range (ledger.py reviewed)")
    if lacking:
        print("RESULT not verified: " + "; ".join(lacking))
        return 2
    print(f"  review: recorded for {end_review[-1]['range'][:12]}..")
    print("RESULT pass")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def named(p):
        p.add_argument("--name", help="ledger name (default: the plan's file name, or the ledger used last)")
        return p

    brief = named(sub.add_parser("brief", help="print a task as a standalone brief for a fresh agent"))
    brief.add_argument("task")
    brief.add_argument("--plan", help="plan file (default: the plan of the current ledger)")
    brief.set_defaults(run=cmd_brief)

    one = named(sub.add_parser("start", help="record that a task starts"))
    one.add_argument("task")
    one.add_argument("--plan", help="plan file to read the task's files and check from")
    one.add_argument("--files", help="comma-separated files the task may touch (a folder ends with /; globs allowed)")
    one.add_argument("--check", help="the task's own test command")
    one.add_argument("--review", choices=["end", "per-task"], help="set once, on the first start (default: end)")
    one.add_argument("--restart", action="store_true", help="record a new start commit for a task that was started before")
    one.set_defaults(run=cmd_start)
    two = named(sub.add_parser("done", help="run the task's check and log completion on success"))
    two.add_argument("task")
    two.add_argument("--accept-outside", metavar="REASON", help="log completion although files outside the list changed, with the reason")
    two.add_argument("--timeout", type=int, default=900, help="seconds before the check is stopped (default 900)")
    two.set_defaults(run=cmd_done)
    three = named(sub.add_parser("finish", help="run the full suite once after the last task"))
    three.add_argument("--suite", required=True, help="the project's full test command")
    three.add_argument("--timeout", type=int, default=3600, help="seconds before the suite is stopped (default 3600)")
    three.set_defaults(run=cmd_finish)
    four = named(sub.add_parser("reviewed", help="record a review from its findings file"))
    four.add_argument("--findings", required=True, help="the file the review wrote")
    four.add_argument("--task", help="the review covers this task only (per-task mode)")
    four.set_defaults(run=cmd_reviewed)
    five = named(sub.add_parser("status", help="show the ledger and what is missing"))
    five.set_defaults(run=cmd_status)
    args = parser.parse_args()
    root = find_root()
    if root is None:
        print("RESULT blocked: not inside a git repository; the ledger ties tasks to commits")
        return 2
    return args.run(root, args)


if __name__ == "__main__":
    sys.exit(main())

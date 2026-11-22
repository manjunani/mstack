#!/usr/bin/env python3
"""Check a plan file before anyone builds from it.

  lint <plan.md>    check the plan; print one line per problem
  tasks <plan.md>   print the tasks the script found, as JSON (what a builder or another script will see)

A plan is a Markdown file. Each task is a heading and five fields:

  ## Task 1: Parse the date header
  Files: src/dates.py, tests/test_dates.py (new)
  Uses: read_header
  Makes: parse_date, DateError
  Check: `python3 -m pytest tests/test_dates.py -q`
  Expect: 4 passed

  Files    every file the task may touch; mark a file the task creates with (new)
  Uses     names (functions, types, tables, routes) the task needs from an earlier task or from the code
  Makes    names the task creates for later tasks
  Check    one command that proves the task
  Expect   what that command prints or returns when the task is right

A field may be one line with commas, or the field name followed by "- item" lines. Uses and Makes may be left out.
The header may carry "Spec: <path>"; the plan is then compared with the spec for size.

lint fails when: a task lacks Files, Check or Expect; Expect says nothing checkable; a listed file is missing and
not marked (new); a filler phrase stands in for a decision; a name is used before a task makes it, is made by no
task and is not in the project, or is spelled differently in two places; task numbers are out of order.
lint warns on: a plan several times longer than its spec, a task with many files, a check program that is not
on this machine. Limits come from references/limits.json.

Exit codes: 0 = the plan passes (warnings may remain), 1 = at least one problem, 2 = blocked: no such file, or not a plan.
This script reads the plan and the project. It writes nothing.
"""
import argparse
import difflib
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys

GIT = os.environ.get("MSTACK_GIT") or "git"
HERE = pathlib.Path(__file__).resolve().parent
TASK = re.compile(r"^##\s+Task\s+(\d+)\s*[:.\-]?\s*(.*?)\s*$", re.I)
FIELD = re.compile(r"^\**(Files|Uses|Makes|Check|Expect)\**\s*:\**\s*(.*)$", re.I)
HEADER = re.compile(r"^\**(Goal|Spec)\**\s*:\**\s*(.*)$", re.I)
BULLET = re.compile(r"^\s*[-*]\s+(.*)$")
IDENT = re.compile(r"`([A-Za-z_][A-Za-z0-9_\-]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)(?:\(\))?`")
FILLER = [
    (r"\bTBD\b", "TBD"), (r"\bTODO\b", "TODO"), (r"\bFIXME\b", "FIXME"), (r"\betc\b\.?", "etc"),
    (r"\band so on\b", "and so on"), (r"\bas needed\b", "as needed"), (r"\bas appropriate\b", "as appropriate"),
    (r"\bappropriately\b", "appropriately"), (r"\bif necessary\b", "if necessary"), (r"\bwhere necessary\b", "where necessary"),
    (r"\bsimilar to (the )?(above|previous|task \d+)\b", "similar to above"), (r"\bsame as (above|before)\b", "same as above"),
    (r"\bhandle (the )?edge cases\b", "handle edge cases"), (r"\badd (proper |appropriate )?error handling\b", "add error handling"),
    (r"\bplaceholder\b", "placeholder"), (r"\bfill (this )?in\b", "fill in"), (r"\bsomehow\b", "somehow"),
    (r"\bfigure out\b", "figure out"), (r"\bvarious\b", "various"), (r"\bthe rest of\b", "the rest of"),
    (r"^\s*(\.\.\.|…)\s*$", "..."), (r"\bto be decided\b", "to be decided"), (r"\bwrite (the )?tests\b\s*$", "write tests"),
]
VAGUE_EXPECT = {"works", "it works", "ok", "okay", "fine", "good", "success", "succeeds", "should work", "as expected",
                "works as expected", "no errors", "no error", "passes", "pass", "tests pass", "green", "done", "correct"}
SKIP_DIRS = {".git", "node_modules", ".mstack", "dist", "build", "target", ".venv", "venv", "__pycache__", ".next", "vendor"}
SCAN_CAP = 4000


def load_limits():
    path = HERE.parent / "references" / "limits.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def split_items(text):
    items = []
    for part in re.split(r",(?![^()]*\))", text):
        part = part.strip().strip("`").strip()
        if part:
            items.append(part)
    return items


def parse(text):
    """Return (header, tasks). A task is a dict with number, title, line, fields and body lines."""
    header, tasks, current, field, fence = {}, [], None, None, False
    for number, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith("```"):
            fence = not fence
            if current:
                current["body"].append((number, line, True))
            field = None
            continue
        match = None if fence else TASK.match(line)
        if match:
            current = {"number": int(match.group(1)), "title": match.group(2), "line": number, "body": [],
                       "files": [], "uses": [], "makes": [], "check": "", "expect": "", "seen": {}}
            tasks.append(current)
            field = None
            continue
        if current is None:
            match = HEADER.match(line)
            if match:
                header[match.group(1).lower()] = match.group(2).strip().strip("`")
            continue
        if not fence and line.startswith("## "):
            current, field = None, None
            continue
        current["body"].append((number, line, fence))
        if fence:
            continue
        match = FIELD.match(line.strip())
        if match:
            field = match.group(1).lower()
            value = match.group(2).strip()
            current["seen"][field] = number
            if field in ("check", "expect"):
                current[field] = value.strip("`").strip() if field == "check" else value
            else:
                current[field].extend(split_items(value))
            continue
        bullet = BULLET.match(line)
        if field in ("files", "uses", "makes") and bullet:
            current[field].extend(split_items(bullet.group(1)))
        elif field in ("check", "expect") and bullet and not current[field]:
            current[field] = bullet.group(1).strip().strip("`").strip()
        elif line.strip():
            field = None
    return header, tasks


def file_entry(item):
    new = bool(re.search(r"\((new|create[sd]?)\)", item, re.I))
    path = re.sub(r"\s*\([^)]*\)\s*", "", item).strip().strip("`")
    return path, new


def project_files(root):
    try:
        out = subprocess.run([GIT, "-C", str(root), "ls-files", "-co", "--exclude-standard"], capture_output=True, text=True, timeout=60)
        if out.returncode == 0 and out.stdout.strip():
            return [root / p for p in out.stdout.splitlines() if not p.startswith(".mstack/")]
    except (OSError, subprocess.TimeoutExpired):
        pass
    found = []
    for folder, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        found.extend(pathlib.Path(folder) / n for n in names)
    return found


def in_project(root, name, plan_path, cache):
    """True if the name appears as a whole word in a project file. None if the scan hit its cap."""
    if "files" not in cache:
        cache["files"] = [p for p in project_files(root) if p.resolve() != plan_path.resolve()]
    word = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])")
    for index, path in enumerate(cache["files"]):
        if index >= SCAN_CAP:
            return None
        try:
            if path.stat().st_size > 1_000_000:
                continue
            if word.search(path.read_text(encoding="utf-8", errors="ignore")):
                return True
        except OSError:
            continue
    return False


def norm(name):
    return re.sub(r"[_\-.]", "", name).lower()


def lint(plan_path, root):
    text = plan_path.read_text(encoding="utf-8", errors="replace")
    header, tasks = parse(text)
    problems, warnings = [], []
    limits = load_limits()

    def limit(key, default):
        entry = limits.get(key, {})
        return entry.get("value", default), entry.get("verified", False)

    if not tasks:
        return None, [], [], header, tasks

    numbers = [t["number"] for t in tasks]
    if numbers != list(range(1, len(tasks) + 1)):
        problems.append((tasks[0]["line"], f"task numbers are {numbers}; they must run 1, 2, 3 with no gap or repeat"))

    makes, created, cache = {}, set(), {}
    for task in tasks:
        for name in task["makes"]:
            makes.setdefault(name, task["number"])

    for task in tasks:
        where = f"task {task['number']}"
        for field in ("files", "check", "expect"):
            if not task[field]:
                problems.append((task["seen"].get(field, task["line"]), f"{where} has no {field.capitalize()}"))
        if not task["title"]:
            problems.append((task["line"], f"{where} has no title"))

        for item in task["files"]:
            path, new = file_entry(item)
            if not path or " " in path or path.lower() in ("various", "several", "multiple", "all"):
                problems.append((task["seen"].get("files", task["line"]), f"{where}: '{item}' is not a file path"))
                continue
            exists = (root / path).exists() or any(ch in path for ch in "*?[") and any(root.glob(path))
            if new:
                created.add(path)
            elif not exists and path not in created:
                problems.append((task["seen"].get("files", task["line"]),
                                 f"{where}: {path} does not exist; write (new) after it if this task creates it"))
        big, _ = limit("max_files_per_task", 6)
        if len(task["files"]) > big:
            warnings.append((task["line"], f"{where} lists {len(task['files'])} files (limit {big}); consider splitting it"))

        if task["check"]:
            try:
                program = shlex.split(task["check"])[0]
            except (ValueError, IndexError):
                program = ""
            if not program or re.match(r"(?i)^(manual|manually|n/?a|none|tbd)\b", task["check"]):
                problems.append((task["seen"]["check"], f"{where}: Check is not a command: '{task['check']}'"))
            elif "=" not in program and shutil.which(program) is None and not (root / program).exists():
                warnings.append((task["seen"]["check"], f"{where}: check program '{program}' is not on this machine"))
        if task["expect"] and task["expect"].strip().strip(".`").lower() in VAGUE_EXPECT:
            problems.append((task["seen"]["expect"], f"{where}: Expect '{task['expect']}' cannot be compared with output; "
                                                     f"write what the command prints (a count, a line, an exit code)"))

        for number, line, fence in task["body"]:
            for pattern, label in FILLER:
                if fence and label not in ("...", "TODO", "TBD", "placeholder", "the rest of"):
                    continue
                if re.search(pattern, line, re.I if label not in ("TBD", "TODO", "FIXME") else 0):
                    problems.append((number, f"{where}: filler '{label}' stands in for a decision: {line.strip()[:70]}"))
                    break

        for name in task["uses"]:
            line = task["seen"].get("uses", task["line"])
            maker = makes.get(name)
            if maker is not None and maker < task["number"]:
                continue
            if maker is not None:
                problems.append((line, f"{where} uses `{name}`, which task {maker} makes later; reorder the tasks"))
                continue
            twins = [m for m in makes if norm(m) == norm(name)]
            close = twins or difflib.get_close_matches(name, list(makes), n=1, cutoff=0.8)
            found = in_project(root, name, plan_path, cache)
            if found:
                continue
            if close:
                problems.append((line, f"{where} uses `{name}`, but the plan makes `{close[0]}` (task {makes[close[0]]}); the names differ"))
            elif found is None:
                warnings.append((line, f"{where} uses `{name}`: not made by an earlier task, and the project is too large to search fully"))
            else:
                problems.append((line, f"{where} uses `{name}`: no earlier task makes it and it is not in the project"))

        for number, line, fence in task["body"]:
            for token in IDENT.findall(line):
                for made in makes:
                    if token != made and norm(token) == norm(made) and token not in makes:
                        problems.append((number, f"{where} writes `{token}`, but task {makes[made]} makes `{made}`; one name, one spelling"))

    seen = {}
    for name, number in sorted(makes.items()):
        twin = seen.get(norm(name))
        if twin and twin != name:
            problems.append((tasks[0]["line"], f"the plan makes both `{twin}` and `{name}`; one name, one spelling"))
        seen[norm(name)] = name

    spec = header.get("spec", "")
    if spec and spec.lower() not in ("none", "-", "n/a"):
        spec_path = root / spec
        if not spec_path.exists():
            problems.append((1, f"Spec: {spec} does not exist"))
        else:
            ratio, verified = limit("max_plan_to_spec_ratio", 3)
            plan_words = len(text.split())
            spec_words = max(1, len(spec_path.read_text(encoding="utf-8", errors="replace").split()))
            if plan_words / spec_words > ratio:
                note = "" if verified else " (limit is mstack's own first setting, not a measured value)"
                warnings.append((1, f"the plan has {plan_words} words, the spec {spec_words}: more than {ratio} times longer{note}"))
    return True, sorted(set(problems)), sorted(set(warnings)), header, tasks


def cmd_lint(args):
    plan = pathlib.Path(args.plan)
    if not plan.is_file():
        print(f"RESULT blocked: {args.plan} is not a file")
        return 2
    root = pathlib.Path(args.root).resolve()
    found, problems, warnings, header, tasks = lint(plan, root)
    if found is None:
        print("no '## Task N: title' heading found")
        print("RESULT blocked: this file is not a plan in the expected shape. Run plan_lint.py --help for the shape")
        return 2
    print(f"plan: {plan}  tasks: {len(tasks)}  project: {root}")
    for line, message in problems:
        print(f"FAIL line {line}: {message}")
    for line, message in warnings:
        print(f"warn line {line}: {message}")
    print(f"checked: fields, files, filler, names across tasks, order, size. {len(problems)} problems, {len(warnings)} warnings")
    if problems:
        print(f"RESULT fail: {len(problems)} problems in the plan")
        return 1
    print("RESULT pass")
    return 0


def cmd_tasks(args):
    plan = pathlib.Path(args.plan)
    if not plan.is_file():
        print(f"RESULT blocked: {args.plan} is not a file")
        return 2
    header, tasks = parse(plan.read_text(encoding="utf-8", errors="replace"))
    if not tasks:
        print("RESULT blocked: no tasks found")
        return 2
    out = [{"number": t["number"], "title": t["title"], "files": [file_entry(f)[0] for f in t["files"]],
            "uses": t["uses"], "makes": t["makes"], "check": t["check"], "expect": t["expect"]} for t in tasks]
    print(json.dumps({"goal": header.get("goal", ""), "spec": header.get("spec", ""), "tasks": out}, indent=2))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("lint", help="check the plan")
    one.add_argument("plan")
    one.add_argument("--root", default=".", help="project folder the plan's paths are relative to (default: current folder)")
    one.set_defaults(run=cmd_lint)
    two = sub.add_parser("tasks", help="print the parsed tasks as JSON")
    two.add_argument("plan")
    two.set_defaults(run=cmd_tasks)
    args = parser.parse_args()
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())

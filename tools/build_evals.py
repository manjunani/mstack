#!/usr/bin/env python3
"""Turn each pack's tests/<skill>.json into eval cases that `claude plugin eval` can run.

For every skill it writes, under packs/<pack>/evals/:
  <skill>.fire.NN/    a prompt where the skill must start
  <skill>.quiet.NN/   a prompt where it must stay quiet
  <skill>.task.NAME/  a real task with its own graders

The evals folders are generated: edit tests/<skill>.json, never the generated files.
A results/ folder inside evals/ (written by `claude plugin eval`) is kept.

Task keys besides name, prompt, max_turns, allowed_tools and graders:
  "fixture": "fixtures/<skill>/<task>"   folder (relative to tests/) whose files are put into the workspace.
      The case gets a case.yaml and a generated scaffold.sh that writes those files, so the
      run needs `claude plugin eval ... --scaffold`. Text files may hold @@FAKE_<NAME>@@ markers
      (see FAKES); the scaffold puts a fake but realistic-looking secret there, so the
      committed fixture never holds a complete token.
  "git": [step, ...]   make the workspace a git repository. With "git", only the fixture
      sub-folders named by steps are written. Each step is an object; its keys run in this order:
        checkout: "<branch>"    switch to an existing branch
        branch: "<name>"        create a branch and switch to it
        remove: ["<path>", ...] delete paths from the working tree
        files: "<sub-folder>"   copy that fixture sub-folder over the working tree
        stage: ["<path>", ...]  git add these paths ("." for everything)
        commit: "<message>"     git add -A, then commit (fixed author and dates)
        merge: "<branch>"       merge that branch into the current one (--no-ff)
        tag: "<name>"           annotated tag on HEAD
  "needs": "<tool>", "skip_reason": "<why>"   the task cannot run without a tool or service the
      eval sandbox does not have. Such tasks are left out unless --include-needs is given.

Exit 0 = written, 1 = a tests file is invalid.
"""
import argparse
import base64
import json
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import common  # noqa: E402

READ_ONLY = ["Read", "Glob", "Grep", "Skill"]
STEP_ORDER = ["checkout", "branch", "remove", "files", "stage", "commit", "merge", "tag"]

# Fake secrets for secret-detection tasks. Each is stored in parts so that neither this file nor a
# fixture holds a complete token; only the generated scaffold (under evals/, not committed) joins them.
FAKES = {
    "AWS_KEY_ID": ["AK", "IA", "R4WQ7TZ2M9XK3BNV"],
    "AWS_SECRET": ["q8Vd3", "LmT0xRz9KpW2", "sJ7nYb4HcE6uFg1AoQ5iZ"],
    "GITHUB_TOKEN": ["gh", "p_", "T7mK2qW9xR4vB8nL3cZ6pY1sD5fH0jG2aE7u"],
    "STRIPE_KEY": ["sk", "_live_", "51Hq8ZtR3mW7vK2xN9pL4cB6"],
    "SLACK_TOKEN": ["xo", "xb-", "2847193650-5839201746-Rk7Qm2Wv9Xt4Lp8N"],
    "PRIVATE_KEY": ["-----BEGIN ", "RSA PRIVATE KEY-----\n", "MIIBOgIBAAJBAKj34GkxFhD90vcNLYLInFEX6Ppy1tPf9Cnzj4p4WGeKLs1Pt8Qu\n",
                    "-----END ", "RSA PRIVATE KEY-----"],
}


def yaml_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(yaml_value(v) for v in value) + "]"
    text = str(value)
    if text and all(c.isalnum() or c in "_-./" for c in text):
        return text
    return "'" + text.replace("'", "''") + "'"


def front(fields):
    return "---\n" + "".join(f"{k}: {yaml_value(v)}\n" for k, v in fields.items()) + "---\n"


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def skill_pattern(pack, name):
    # The pack prefix is required: Claude Code has built-in skills with plain names such as "verify",
    # and a call to one of those must not count as this skill starting.
    return r'"skill"\s*:\s*"mstack-' + pack + ":" + name + '"'


def sh(text):
    return "'" + str(text).replace("'", "'\\''") + "'"


def emit_files(src, lines, used):
    """Shell lines that recreate every file under src (relative paths kept) in the current directory."""
    files = sorted(p for p in src.rglob("*") if p.is_file() and p.name != ".DS_Store")
    for path in files:
        rel = path.relative_to(src).as_posix()
        data = path.read_bytes()
        parent = pathlib.PurePosixPath(rel).parent
        if str(parent) != ".":
            lines.append(f"mkdir -p {sh(parent)}")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = None
        if text is not None and text.endswith("\n") and "\0" not in text:
            mark = "MSTACK_EOF"
            while mark in text:
                mark += "_"
            lines.append(f"cat > {sh(rel)} <<'{mark}'\n{text}{mark}")
            fakes = [name for name in FAKES if f"@@FAKE_{name}@@" in text]
            if fakes:
                used.update(fakes)
                lines.append(f"put_fakes {sh(rel)}")
        else:
            encoded = base64.b64encode(data).decode("ascii")
            chunks = "\n".join(encoded[i:i + 76] for i in range(0, len(encoded), 76))
            lines.append(f"base64 -d > {sh(rel)} <<'MSTACK_B64'\n{chunks}\nMSTACK_B64")
        if path.stat().st_mode & 0o111:
            lines.append(f"chmod +x {sh(rel)}")


def scaffold(task, tests_dir, where):
    """Return the scaffold.sh text for a task with a fixture, or None."""
    if "fixture" not in task:
        if "git" in task:
            raise ValueError(f"{where}: 'git' needs a 'fixture' folder")
        return None
    src = (tests_dir / task["fixture"]).resolve()
    if not src.is_dir() or tests_dir.resolve() not in src.parents:
        raise ValueError(f"{where}: fixture folder {task['fixture']} not found under tests/")
    body, used = [], set()
    steps = task.get("git")
    if steps is None:
        emit_files(src, body, used)
    else:
        named = set()
        body += ["git init -q", "git symbolic-ref HEAD refs/heads/main",
                 "git config user.name 'Sam Example'", "git config user.email sam@example.test",
                 "git config commit.gpgsign false", "git config tag.gpgsign false"]
        day = 0
        for n, step in enumerate(steps, 1):
            unknown = set(step) - set(STEP_ORDER)
            if unknown:
                raise ValueError(f"{where}: git step {n} has unknown keys {sorted(unknown)}")
            for key in [k for k in STEP_ORDER if k in step]:
                value = step[key]
                if key == "checkout":
                    body.append(f"git checkout -q {sh(value)}")
                elif key == "branch":
                    body.append(f"git checkout -q -b {sh(value)}")
                elif key == "remove":
                    body.append("rm -rf -- " + " ".join(sh(p) for p in value))
                elif key == "files":
                    sub = src / value
                    if not sub.is_dir():
                        raise ValueError(f"{where}: git step {n}: fixture sub-folder {value} not found")
                    named.add(pathlib.PurePosixPath(value).parts[0])
                    emit_files(sub, body, used)
                elif key == "stage":
                    body.append("git add -- " + " ".join(sh(p) for p in value))
                elif key in ("commit", "merge"):
                    day += 1
                    stamp = f"2026-01-{day:02d}T10:00:00+0000"
                    body.append(f"export GIT_AUTHOR_DATE={stamp} GIT_COMMITTER_DATE={stamp}")
                    if key == "commit":
                        body.append(f"git add -A && git commit -q -m {sh(value)}")
                    else:
                        body.append(f"git merge -q --no-ff -m {sh('Merge ' + value)} {sh(value)}")
                elif key == "tag":
                    body.append(f"git tag -a {sh(value)} -m {sh(value)}")
        stray = sorted(p.name for p in src.iterdir() if p.name not in named and p.name != ".DS_Store")
        if stray:
            raise ValueError(f"{where}: fixture entries not used by any git step: {stray}")
    head = ["#!/usr/bin/env bash",
            f"# Generated by tools/build_evals.py from tests/{task['fixture']}. Do not edit.",
            "# Writes the task's fixture files into the empty eval workspace.",
            "set -euo pipefail"]
    if used:
        head.append("# Fake secrets, joined here so that no committed file holds a complete token.")
        for name in sorted(used):
            head.append(f"FAKE_{name}=" + "".join("$'" + part.replace("\n", "\\n") + "'" for part in FAKES[name]))
        head.append("put_fakes() {")
        head.append('  local c; c=$(cat "$1")')
        for name in sorted(used):
            head.append(f'  c=${{c//@@FAKE_{name}@@/$FAKE_{name}}}')
        head.append("  printf '%s\\n' \"$c\" > \"$1\"")
        head.append("}")
    return "\n".join(head + body) + "\n"


def build_pack(pack, smoke=0, tasks_only=False, include_needs=False):
    """smoke > 0 writes only the first `smoke` fire and quiet prompts per skill, no tasks, into evals-smoke/.
    tasks_only rewrites only the *.task.* cases and leaves fire and quiet cases alone."""
    tests_dir, evals = pack / "tests", pack / ("evals-smoke" if smoke else "evals")
    if evals.exists():
        for old in evals.iterdir():
            if old.is_dir() and old.name != "results" and (".task." in old.name or not tasks_only):
                shutil.rmtree(old)
    made = skipped = 0
    for path in sorted(tests_dir.glob("*.json")) if tests_dir.is_dir() else []:
        if path.name == "results.json":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        name = path.stem
        if not (pack / "skills" / name / "SKILL.md").exists():
            continue
        for kind, limits in [] if tasks_only else (("fire", {}), ("quiet", {"min": 0, "max": 0})):
            prompts = data.get(kind, [])
            for i, prompt in enumerate(prompts[:smoke] if smoke else prompts, 1):
                case = evals / f"{name}.{kind}.{i:02d}"
                write(case / "prompt.md", front({"max_turns": 3, "allowed_tools": READ_ONLY}) + prompt.strip() + "\n")
                grader = {"type": "tool_used", "tool": "Skill", "input_match": skill_pattern(pack.name, name), "arm": "both", **limits}
                write(case / "graders" / f"{kind}.md", front(grader))
                made += 1
        for task in [] if smoke else data.get("tasks", []):
            where = f"{path.name} task {task.get('name')}"
            if "needs" in task and not task.get("skip_reason"):
                raise ValueError(f"{where}: 'needs' requires a 'skip_reason'")
            if "needs" in task and not include_needs:
                skipped += 1
                continue
            case_name = f"{name}.task.{task['name']}"
            case = evals / case_name
            script = scaffold(task, tests_dir, where)
            head = {"max_turns": task.get("max_turns", 15), "allowed_tools": task.get("allowed_tools", READ_ONLY)}
            tags = (["scaffold"] if script else []) + (["needs-" + task["needs"]] if "needs" in task else [])
            if tags:
                head["tags"] = tags
            write(case / "prompt.md", front(head) + task["prompt"].strip() + "\n")
            if script:
                write(case / "scaffold.sh", script)
                (case / "scaffold.sh").chmod(0o755)
                write(case / "case.yaml", f'schema_version: "1.1"\nname: {case_name}\ncontext:\n  scaffold_script: scaffold.sh\n')
            for n, grader in enumerate(task["graders"], 1):
                body = grader.get("body", "")
                fields = {k: v for k, v in grader.items() if k not in ("body", "name")}
                write(case / "graders" / f"{grader.get('name', f'check{n}')}.md", front(fields) + (body.strip() + "\n" if body else ""))
            made += 1
    return made, skipped


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pack", nargs="?", help="pack folder name, for example core (default: all packs)")
    parser.add_argument("--root", type=pathlib.Path, default=common.ROOT, help="repository root (default: this repository)")
    parser.add_argument("--smoke", type=int, default=0, help="write only N fire and N quiet cases per skill, into evals-smoke/")
    parser.add_argument("--tasks-only", action="store_true", help="rewrite only the task cases; leave fire and quiet cases as they are")
    parser.add_argument("--include-needs", action="store_true", help="also write tasks marked with 'needs' (tagged needs-<tool>)")
    args = parser.parse_args()
    total = skipped_total = 0
    for pack in common.packs(args.root):
        if args.pack and pack.name != args.pack:
            continue
        try:
            made, skipped = build_pack(pack, args.smoke, args.tasks_only, args.include_needs)
        except (ValueError, KeyError) as exc:
            print(f"FAIL {pack.name}: {exc}", file=sys.stderr)
            return 1
        print(f"{pack.name}: {made} eval cases" + (f" ({skipped} tasks left out: they need a tool, see 'needs')" if skipped else ""))
        total += made
        skipped_total += skipped
    print(f"evals built: {total} cases" + (f", {skipped_total} tasks left out" if skipped_total else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

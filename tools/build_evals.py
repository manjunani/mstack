#!/usr/bin/env python3
"""Turn each pack's tests/<skill>.json into eval cases that `claude plugin eval` can run.

For every skill it writes, under packs/<pack>/evals/:
  <skill>.fire.NN/    a prompt where the skill must start
  <skill>.quiet.NN/   a prompt where it must stay quiet
  <skill>.task.NAME/  a real task with its own graders

The evals folders are generated: edit tests/<skill>.json, never the generated files.
Exit 0 = written, 1 = a tests file is invalid.
"""
import argparse
import json
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import common  # noqa: E402

READ_ONLY = ["Read", "Glob", "Grep", "Skill"]


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


def build_pack(pack, smoke=0):
    """smoke > 0 writes only the first `smoke` fire and quiet prompts per skill, no tasks, into evals-smoke/."""
    tests_dir, evals = pack / "tests", pack / ("evals-smoke" if smoke else "evals")
    if evals.exists():
        shutil.rmtree(evals)
    made = 0
    for path in sorted(tests_dir.glob("*.json")) if tests_dir.is_dir() else []:
        if path.name == "results.json":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        name = path.stem
        if not (pack / "skills" / name / "SKILL.md").exists():
            continue
        for kind, limits in (("fire", {}), ("quiet", {"min": 0, "max": 0})):
            prompts = data.get(kind, [])
            for i, prompt in enumerate(prompts[:smoke] if smoke else prompts, 1):
                case = evals / f"{name}.{kind}.{i:02d}"
                write(case / "prompt.md", front({"max_turns": 3, "allowed_tools": READ_ONLY}) + prompt.strip() + "\n")
                grader = {"type": "tool_used", "tool": "Skill", "input_match": skill_pattern(pack.name, name), "arm": "both", **limits}
                write(case / "graders" / f"{kind}.md", front(grader))
                made += 1
        for task in [] if smoke else data.get("tasks", []):
            case = evals / f"{name}.task.{task['name']}"
            head = {"max_turns": task.get("max_turns", 15), "allowed_tools": task.get("allowed_tools", READ_ONLY)}
            write(case / "prompt.md", front(head) + task["prompt"].strip() + "\n")
            for n, grader in enumerate(task["graders"], 1):
                body = grader.get("body", "")
                fields = {k: v for k, v in grader.items() if k not in ("body", "name")}
                write(case / "graders" / f"{grader.get('name', f'check{n}')}.md", front(fields) + (body.strip() + "\n" if body else ""))
            made += 1
    return made


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pack", nargs="?", help="pack folder name, for example core (default: all packs)")
    parser.add_argument("--root", type=pathlib.Path, default=common.ROOT, help="repository root (default: this repository)")
    parser.add_argument("--smoke", type=int, default=0, help="write only N fire and N quiet cases per skill, into evals-smoke/")
    args = parser.parse_args()
    total = 0
    for pack in common.packs(args.root):
        if args.pack and pack.name != args.pack:
            continue
        try:
            made = build_pack(pack, args.smoke)
        except (ValueError, KeyError) as exc:
            print(f"FAIL {pack.name}: {exc}", file=sys.stderr)
            return 1
        print(f"{pack.name}: {made} eval cases")
        total += made
    print(f"evals built: {total} cases")
    return 0


if __name__ == "__main__":
    sys.exit(main())

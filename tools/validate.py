#!/usr/bin/env python3
"""Check every mstack skill against standard/RULES.md and standard/DESCRIPTIONS.md.

Exit 0 = all rules pass, 1 = at least one failure. Warnings do not fail unless --strict.
This checks mstack's own rules. Run `claude plugin validate . --strict` as well for the plugin format.
"""
import argparse
import ast
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import common  # noqa: E402

NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+){0,2}$")
PRESSURE = re.compile(r"\b(always|must|critical|mandatory|before anything else|never skip)\b", re.I)
UNCLEAN = re.compile(r"ignore (all |any )?(previous|prior|other) (instructions|rules)|star (this|the) repo|follow us|sponsored by|npx skills add|/plugin install", re.I)
SECTIONS = ["## Done when", "## Needs", "## Steps", "## Not for", "## Level"]
STATES = ["pass", "fail", "not verified", "blocked"]
STOP = set("a an the and or of to in on for with is are be it this that when user users asks ask wants want needs need was were has have about from".split())


def tokens(text):
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP and len(w) > 2}


def check_script(path, problems):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        problems.append(f"{path.name}: does not parse ({exc.msg}, line {exc.lineno})")
        return
    local = {p.stem for p in path.parent.glob("*.py")}
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])
    outside = sorted(m for m in imported if m not in sys.stdlib_module_names and m not in local)
    if outside:
        problems.append(f"{path.name}: imports outside the standard library: {', '.join(outside)}")
    if "argparse" not in imported:
        problems.append(f"{path.name}: no argparse, so no --help")


def check_skill(pack, manifest, folder, strict_tests):
    problems, warnings = [], []
    fields, body = common.read_skill(folder)
    if not fields:
        return ["no frontmatter at line 1"], warnings, ""
    name = fields.get("name", "")
    desc = fields.get("description", "")
    meta = fields.get("metadata") if isinstance(fields.get("metadata"), dict) else {}

    if name != folder.name:
        problems.append(f"name '{name}' does not match folder '{folder.name}'")
    if not NAME.match(name):
        problems.append("name must be lower case, at most three words joined by hyphens")
    if meta.get("pack") != pack.name:
        problems.append(f"metadata.pack is '{meta.get('pack')}', expected '{pack.name}'")
    if "version" not in meta or "needs" not in meta:
        problems.append("metadata needs both version and needs")

    if len(desc) > 1024:
        problems.append(f"description is {len(desc)} characters; the limit is 1024")
    elif not 250 <= len(desc) <= 600:
        warnings.append(f"description is {len(desc)} characters; aim for 250 to 600")
    if not re.search(r"\bUse when\b", desc):
        problems.append("description has no 'Use when'")
    if not re.search(r"\bNot for\b", desc):
        problems.append("description has no 'Not for' naming the neighbouring skill")
    if "use when" not in desc[:260].lower():
        warnings.append("'Use when' starts after character 260; put the trigger earlier")
    hit = PRESSURE.search(desc)
    if hit:
        problems.append(f"description uses a pressure word: '{hit.group(0)}'")
    if "<" in desc and ">" in desc:
        problems.append("description still contains template placeholders")

    lines = body.strip().splitlines()
    if len(lines) > 150:
        problems.append(f"body is {len(lines)} lines; the limit is 150")
    positions = {s: body.find(s) for s in SECTIONS}
    for section, pos in positions.items():
        if pos == -1:
            problems.append(f"missing section '{section}'")
    if positions["## Done when"] > positions["## Steps"] > -1:
        problems.append("'Done when' must come before 'Steps'")
    lowered = body.lower()
    for state in STATES:
        if state not in lowered:
            problems.append(f"end state '{state}' is not mentioned")
    hit = UNCLEAN.search(body) or UNCLEAN.search(desc)
    if hit:
        problems.append(f"text that does not belong in a skill: '{hit.group(0)}'")

    scripts = folder / "scripts"
    script_files = sorted(scripts.glob("*.py")) if scripts.is_dir() else []
    for script in script_files:
        check_script(script, problems)
    if not script_files and not re.search(r"```", body):
        problems.append("runs nothing: no scripts/ and no command in the body (rule 2)")
    for ref in re.findall(r"scripts/([\w.-]+)", body):
        if not (scripts / ref).exists():
            problems.append(f"body refers to scripts/{ref}, which does not exist")

    tests = pack / "tests" / f"{name}.json"
    if not tests.exists():
        (problems if strict_tests else warnings).append(f"no tests file tests/{name}.json")
    else:
        try:
            data = json.loads(tests.read_text(encoding="utf-8"))
            fire, quiet, tasks = data.get("fire", []), data.get("quiet", []), data.get("tasks", [])
            if len(fire) < 10 or len(quiet) < 10:
                problems.append(f"tests need 10 fire and 10 quiet prompts; found {len(fire)} and {len(quiet)}")
            if len(tasks) < 2:
                problems.append(f"tests need at least 2 tasks; found {len(tasks)}")
            plain = sum(1 for p in fire if name not in p.lower() and name.replace("-", " ") not in p.lower())
            if plain < 3:
                problems.append("at least 3 fire prompts must not contain the skill's name")
        except ValueError as exc:
            problems.append(f"tests/{name}.json is not valid JSON: {exc}")
    return problems, warnings, desc


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--strict", action="store_true", help="treat warnings and missing tests as failures")
    parser.add_argument("--root", type=pathlib.Path, default=common.ROOT, help="repository root (default: this repository)")
    args = parser.parse_args()

    failures = warned = count = 0
    seen, clauses = {}, {}
    for pack in common.packs(args.root):
        manifest = common.pack_manifest(pack)
        if manifest is None:
            print(f"FAIL {pack.name}: no .claude-plugin/plugin.json")
            failures += 1
            continue
        if manifest.get("name") != f"mstack-{pack.name}":
            print(f"FAIL {pack.name}: plugin name must be 'mstack-{pack.name}'")
            failures += 1
        for folder in common.skills(pack):
            count += 1
            problems, warnings, desc = check_skill(pack, manifest, folder, args.strict)
            label = f"{pack.name}/{folder.name}"
            if folder.name in seen:
                problems.append(f"name already used in {seen[folder.name]}")
            seen[folder.name] = label
            clauses[label] = tokens(common.use_when(desc))
            for p in problems:
                print(f"FAIL {label}: {p}")
            for w in warnings:
                print(f"warn {label}: {w}")
            failures += len(problems)
            warned += len(warnings)
            if not problems and not warnings:
                print(f"ok   {label}")

    labels = sorted(clauses)
    for i, a in enumerate(labels):
        for b in labels[i + 1:]:
            if clauses[a] and clauses[b]:
                overlap = len(clauses[a] & clauses[b]) / len(clauses[a] | clauses[b])
                if overlap > 0.5:
                    print(f"FAIL collision: {a} and {b} share {overlap:.0%} of their 'Use when' words")
                    failures += 1

    bad = failures or (args.strict and warned)
    print(f"validate: {count} skills, {failures} failures, {warned} warnings: {'FAIL' if bad else 'PASS'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

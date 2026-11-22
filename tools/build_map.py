#!/usr/bin/env python3
"""Build the mstack skill map and everything generated from it.

Writes three things from the SKILL.md files and pack manifests:
  skills.json                        the map of every skill
  .claude-plugin/marketplace.json    one entry per pack
  README.md                          the table between the skills markers

Run with --check to compare instead of write. Exit 0 = up to date, 1 = out of date.
"""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import common  # noqa: E402

START, END = "<!-- skills:start -->", "<!-- skills:end -->"


def collect(root):
    version = (root / "VERSION").read_text(encoding="utf-8").strip() if (root / "VERSION").exists() else "0.0.0"
    out_packs, out_skills = [], []
    for pack in common.packs(root):
        manifest = common.pack_manifest(pack)
        if manifest is None:
            continue
        results_path = pack / "tests" / "results.json"
        results = {}
        if results_path.exists():
            import json
            results = json.loads(results_path.read_text(encoding="utf-8"))
        names = []
        for folder in common.skills(pack):
            fields, _ = common.read_skill(folder)
            if not fields:
                continue
            meta = fields.get("metadata") if isinstance(fields.get("metadata"), dict) else {}
            needs = [n.strip() for n in meta.get("needs", "none").split(",") if n.strip() and n.strip() != "none"]
            name = fields.get("name", folder.name)
            names.append(name)
            out_skills.append({
                "name": name,
                "pack": manifest["name"],
                "description": fields.get("description", ""),
                "needs": needs,
                "version": meta.get("version", manifest.get("version", version)),
                "path": str(folder.relative_to(root)),
                "tests": results.get(name, "not tested"),
            })
        out_packs.append({
            "name": manifest["name"],
            "description": manifest.get("description", ""),
            "version": manifest.get("version", version),
            "source": "./" + str(pack.relative_to(root)),
            "skills": names,
            "install": f"/plugin install {manifest['name']} --marketplace {common.REPO_OWNER}/{common.MARKETPLACE}",
        })
    return version, out_packs, out_skills


def render(root):
    version, packs, skills = collect(root)
    skill_map = {
        "name": common.MARKETPLACE,
        "version": version,
        "marketplace": f"{common.REPO_OWNER}/{common.MARKETPLACE}",
        "packs": packs,
        "skills": skills,
    }
    marketplace = {
        "name": common.MARKETPLACE,
        "owner": {"name": common.REPO_OWNER},
        "metadata": {"description": "Small packs of tested agent skills, one pack per domain.", "version": version},
        "plugins": [
            {"name": p["name"], "source": p["source"], "description": p["description"], "version": p["version"]}
            for p in packs
        ],
    }
    lines = [START, ""]
    for pack in packs:
        lines += [f"### {pack['name']}", "", pack["description"], "", "```", pack["install"], "```", "", "| Skill | What it does | Needs | Tests |", "|---|---|---|---|"]
        for skill in (s for s in skills if s["pack"] == pack["name"]):
            first = skill["description"].split(". ")[0].rstrip(".") + "."
            tests = skill["tests"] if isinstance(skill["tests"], str) else ("smoke: " if skill["tests"].get("kind") == "smoke" else "") + ", ".join(
                f"{k} {skill['tests'][k]}" for k in ("trigger", "silence", "benefit") if k in skill["tests"])
            lines.append(f"| `{skill['name']}` | {first} | {', '.join(skill['needs']) or 'none'} | {tests} |")
        lines.append("")
    lines.append(END)
    table = "\n".join(lines)

    readme_path = root / "README.md"
    readme = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""
    if START in readme and END in readme:
        new_readme = readme[:readme.index(START)] + table + readme[readme.index(END) + len(END):]
    else:
        new_readme = readme
    outputs = {
        root / "skills.json": common.dump_json(skill_map),
        root / ".claude-plugin" / "marketplace.json": common.dump_json(marketplace),
        readme_path: new_readme,
    }
    # A pack is installed without the repository root, so the finder skill carries its own copy of the map.
    finder = root / "packs" / "core" / "skills" / "mstack"
    if finder.is_dir():
        outputs[finder / "references" / "skills.json"] = common.dump_json(skill_map)
    return outputs, len(packs), len(skills)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="compare with the files on disk, write nothing")
    parser.add_argument("--root", type=pathlib.Path, default=common.ROOT, help="repository root (default: this repository)")
    args = parser.parse_args()

    outputs, n_packs, n_skills = render(args.root)
    stale = [p for p, text in outputs.items() if not p.exists() or p.read_text(encoding="utf-8") != text]
    if args.check:
        for path in stale:
            print(f"OUT OF DATE {path.relative_to(args.root)}", file=sys.stderr)
        print(f"map check: {n_packs} packs, {n_skills} skills, {'out of date' if stale else 'up to date'}")
        return 1 if stale else 0
    for path in stale:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(outputs[path], encoding="utf-8")
        print(f"wrote {path.relative_to(args.root)}")
    print(f"map built: {n_packs} packs, {n_skills} skills")
    return 0


if __name__ == "__main__":
    sys.exit(main())

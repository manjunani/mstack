#!/usr/bin/env python3
"""Copy mstack skill folders into another agent's skills folder.

For agents that read the Agent Skills format (a folder with a SKILL.md) but do not use the
Claude Code plugin system, Codex for example. Claude Code users install packs as plugins instead.

Where the skills go (pick one):
  --agent codex      ~/.codex/skills
  --agent project    ./.agents/skills under the current folder
  --to PATH          any folder you name

Each skill folder is copied as mstack-<skill> (for example mstack-verify), and the `name:` line in the
copied SKILL.md is changed to match, so the skills do not clash with others of the same name.
Nothing in this repository is changed.

Options:
  --packs core dev   packs to copy (default: core); short names or mstack-<pack>; `all` for every pack
  --dry-run          print what would be copied, copy nothing
  --force            replace target folders that already have the same name; without it the script
                     refuses and lists them. It never deletes anything else.
  --list             list the packs and their skills, copy nothing

Exit codes: 0 copied (or dry run), 1 refused because folders exist, 2 bad input.

Only the skills are copied. The guard hook in mstack-core works in Claude Code only.
"""
import argparse
import os
import pathlib
import re
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import common  # noqa: E402

PREFIX = "mstack-"
SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")


def available(root):
    """{short pack name: [skill folders]} for every pack with a manifest."""
    out = {}
    for pack in common.packs(root):
        if common.pack_manifest(pack) is not None:
            out[pack.name] = common.skills(pack)
    return out


def target_dir(args):
    if args.to:
        return pathlib.Path(os.path.expanduser(args.to)).resolve()
    if args.agent == "codex":
        return pathlib.Path.home() / ".codex" / "skills"
    return pathlib.Path.cwd() / ".agents" / "skills"


def rename_in_skill(path, new_name):
    """Set the frontmatter `name:` of a copied SKILL.md to new_name."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return
    end = text.find("\n---", 4)
    head, rest = text[:end], text[end:]
    head = re.sub(r"(?m)^name:.*$", f"name: {new_name}", head, count=1)
    path.write_text(head + rest, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    where = parser.add_mutually_exclusive_group()
    where.add_argument("--agent", choices=["codex", "project"], help="codex = ~/.codex/skills, project = ./.agents/skills")
    where.add_argument("--to", help="copy into this folder instead")
    parser.add_argument("--packs", nargs="+", default=["core"], help="packs to copy (default: core), or all")
    parser.add_argument("--dry-run", action="store_true", help="print the plan, copy nothing")
    parser.add_argument("--force", action="store_true", help="replace same-named folders in the target")
    parser.add_argument("--list", action="store_true", help="list packs and skills, copy nothing")
    args = parser.parse_args()

    packs = available(common.ROOT)
    if not packs:
        print(f"no packs found under {common.ROOT / 'packs'}")
        print("RESULT not verified: run this script from a full copy of the mstack repository")
        return 2
    if args.list:
        for name, folders in packs.items():
            print(f"{PREFIX}{name}: {', '.join(f.name for f in folders)}")
        return 0
    if not args.agent and not args.to:
        parser.print_usage()
        print("blocked: choose where to copy with --agent codex, --agent project or --to PATH")
        return 2

    wanted = []
    for raw in args.packs:
        short = raw[len(PREFIX):] if raw.startswith(PREFIX) else raw
        if short == "all":
            wanted = list(packs)
            break
        if short not in packs:
            print(f"unknown pack '{raw}'. Known: {', '.join(packs)}")
            print("blocked: name a pack that exists (see --list)")
            return 2
        if short not in wanted:
            wanted.append(short)

    dest = target_dir(args)
    plan, seen = [], {}
    for short in wanted:
        for folder in packs[short]:
            new = PREFIX + folder.name
            if new in seen:
                print(f"two packs have a skill named {folder.name}: {seen[new]} and {short}")
                print("blocked: copy those packs separately")
                return 2
            seen[new] = short
            plan.append((folder, dest / new))

    existing = [t for _, t in plan if t.exists()]
    if existing and not args.force:
        print(f"{len(existing)} folder(s) already exist in {dest}:")
        for t in existing:
            print(f"  {t.name}")
        print("RESULT fail: nothing copied. Run again with --force to replace these folders, or choose another target.")
        return 1

    verb = "would copy" if args.dry_run else "copied"
    print(f"target: {dest}")
    for source, target in plan:
        replaced = target.exists()
        if not args.dry_run:
            if replaced:
                shutil.rmtree(target)  # only a folder this run is about to recopy
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, target, ignore=SKIP)
            rename_in_skill(target / "SKILL.md", target.name)
        note = (" (would replace existing)" if args.dry_run else " (replaced)") if replaced else ""
        print(f"  {verb} {source.relative_to(common.ROOT)} -> {target.name}{note}")
    print(f"{len(plan)} skill(s) from {len(wanted)} pack(s): {', '.join(PREFIX + w for w in wanted)}")
    if "core" in wanted:
        print("note: the guard hook in mstack-core is not copied; it works in Claude Code only")
    print("RESULT pass" + (" (dry run, nothing copied)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Shared helpers for the mstack tools. Python standard library only."""
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPO_OWNER = "manjunani"
MARKETPLACE = "mstack"


def parse_frontmatter(text):
    """Return (fields, body). Handles plain `key: value` lines and one level of nesting (metadata)."""
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---", 4)
    if end == -1:
        return None, text
    fields, parent = {}, None
    for line in text[4:end].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indented = line.startswith((" ", "\t"))
        key, sep, value = line.strip().partition(":")
        if not sep:
            continue
        value = value.strip().strip("\"'")
        if indented and parent is not None:
            fields[parent][key.strip()] = value
        elif value == "":
            parent = key.strip()
            fields[parent] = {}
        else:
            parent = None
            fields[key.strip()] = value
    body = text[end + 4:]
    return fields, body.lstrip("\n")


def packs(root=ROOT):
    base = root / "packs"
    if not base.is_dir():
        return []
    return sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith((".", "_")))


def pack_manifest(pack):
    path = pack / ".claude-plugin" / "plugin.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def skills(pack):
    base = pack / "skills"
    if not base.is_dir():
        return []
    return sorted(p for p in base.iterdir() if p.is_dir() and (p / "SKILL.md").exists())


def read_skill(folder):
    text = (folder / "SKILL.md").read_text(encoding="utf-8")
    fields, body = parse_frontmatter(text)
    return fields, body


def use_when(description):
    """The 'Use when ...' clause of a description, lower case, without the 'Not for' part."""
    match = re.search(r"\buse (?:it |this )?when\b(.*?)(?:\bnot for\b|$)", description, re.I | re.S)
    return match.group(1).strip().lower() if match else ""


def dump_json(data):
    return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n"

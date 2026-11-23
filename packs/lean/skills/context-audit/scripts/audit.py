#!/usr/bin/env python3
"""Measure what Claude Code loads before the first message, rank it, and say what could be switched off.

Reads, never writes. Looks at:
  instruction files   ~/.claude/CLAUDE.md, ~/.claude/rules/, CLAUDE.md, CLAUDE.local.md, .claude/CLAUDE.md,
                      .claude/rules/ and AGENTS.md in the project and every folder above it (up to the home
                      folder when the project is inside it), the project's
                      auto memory index, and every file they pull in with @path imports
  skill listing       name and description of each skill, command and agent: ~/.claude/skills, the project's
                      .claude/skills, and every enabled plugin
  MCP servers         ~/.claude.json (user and per-project), .mcp.json, settings files, enabled plugins;
                      tool counts come from tool calls seen in transcripts, so they are a lower bound
  output style        the style named in settings, when its file can be found
  hooks               SessionStart and UserPromptSubmit hooks, whose printed text joins the context

Sizes are characters; tokens are an ESTIMATE (characters / chars_per_token from references/thresholds.json).
MCP tool schemas and hook output cannot be sized from files; they are listed as not measured.

Exit 0 = estimated total within the budget, 1 = over the budget, 2 = nothing could be read.
Examples:
  audit.py                                  # this folder, the real home folder
  audit.py --project ~/code/shop --budget 15000 --top 15
  audit.py --home <test-home> --project <test-project>
"""
import argparse
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
IMPORT = re.compile(r"(?:^|\s)@((?:~/|\.{1,2}/|/)?[\w.~/-]+)")


def load_thresholds():
    try:
        data = json.loads((HERE.parent / "references" / "thresholds.json").read_text(encoding="utf-8"))
        return {k: v["value"] for k, v in data.items()}, [k for k, v in data.items() if not v.get("verified")]
    except (OSError, ValueError, KeyError, TypeError):
        return {"chars_per_token": 4, "startup_budget_tokens": 20000, "duplicate_min_chars": 80}, ["all (file unreadable)"]


def read(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def read_json(path):
    text = read(path)
    if text is None:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except ValueError:
        return None


def frontmatter(text):
    """Return the name and description fields of a markdown file's frontmatter (simple YAML subset)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields, key = {}, None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        m = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
        if m:
            key = m.group(1)
            value = m.group(2).strip()
            fields[key] = "" if value in (">", "|", ">-", "|-") else value.strip("'\"")
        elif key and line.startswith((" ", "\t")):
            fields[key] = (fields[key] + " " + line.strip()).strip()
    return fields


class Audit:
    def __init__(self, home, project, cpt):
        self.home, self.project, self.cpt = home, project, cpt
        self.items, self.unmeasured, self.seen = [], [], set()
        self.instruction_texts = {}

    def show(self, path):
        try:
            return "~/" + str(path.relative_to(self.home))
        except ValueError:
            return str(path)

    def add(self, kind, label, chars, action):
        self.items.append({"kind": kind, "label": label, "chars": chars, "tokens": round(chars / self.cpt), "action": action})

    def instruction(self, path, kind, depth=0, parent=None):
        path = path.resolve()
        if path in self.seen or not path.is_file():
            return
        text = read(path)
        if text is None:
            return
        self.seen.add(path)
        if kind == "memory index":
            text = "\n".join(text.splitlines()[:200])
        label = self.show(path) + (f"  (imported by {self.show(parent)})" if parent else "")
        action = "drop the @-import and read the file only when a task needs it" if parent else \
            "shorten it; move detail into a file that is read on demand"
        if path.name == "AGENTS.md" and not parent:
            action += " (counted, but whether your client loads AGENTS.md depends on the client)"
        self.add("import" if parent else kind, label, len(text), action)
        self.instruction_texts[label] = text
        if depth >= 5:
            return
        fenced = False
        for line in text.splitlines():
            if line.strip().startswith("```"):
                fenced = not fenced
            if fenced:
                continue
            for ref in IMPORT.findall(line):
                target = pathlib.Path(ref.replace("~", str(self.home), 1)) if ref.startswith("~") else (path.parent / ref)
                if target.is_file():
                    self.instruction(target, kind, depth + 1, path)

    def instructions(self):
        claude = self.home / ".claude"
        self.instruction(claude / "CLAUDE.md", "user instructions")
        for rule in sorted((claude / "rules").rglob("*.md")) if (claude / "rules").is_dir() else []:
            self.instruction(rule, "user instructions")
        folders = [self.project]
        for parent in self.project.parents:
            folders.append(parent)
            if parent == self.home:
                break
        for folder in folders:
            for name in ("CLAUDE.md", "CLAUDE.local.md", ".claude/CLAUDE.md", "AGENTS.md"):
                self.instruction(folder / name, "project instructions")
            rules = folder / ".claude" / "rules"
            if rules.is_dir() and folder != self.home:
                for rule in sorted(rules.rglob("*.md")):
                    self.instruction(rule, "project instructions")
        slug = re.sub(r"[^A-Za-z0-9]", "-", str(self.project))
        self.instruction(claude / "projects" / slug / "memory" / "MEMORY.md", "memory index")

    def settings(self):
        files = [self.home / ".claude" / "settings.json", self.project / ".claude" / "settings.json",
                 self.project / ".claude" / "settings.local.json"]
        return [(f, d) for f in files if (d := read_json(f)) is not None]

    def plugins(self, settings):
        enabled = {}
        for _, data in settings:
            for name, on in (data.get("enabledPlugins") or {}).items():
                enabled[name] = bool(on)
        installed = (read_json(self.home / ".claude" / "plugins" / "installed_plugins.json") or {}).get("plugins") or {}
        found = []
        for name, on in sorted(enabled.items()):
            if not on:
                continue
            root = None
            entries = installed.get(name)
            if isinstance(entries, list):
                for entry in entries:
                    p = pathlib.Path(str(entry.get("installPath", "")))
                    if p.is_dir():
                        root = p
            if root is None:
                plugin, _, market = name.partition("@")
                versions = sorted((self.home / ".claude" / "plugins" / "cache" / market / plugin).glob("*/"))
                root = versions[-1] if versions else None
            if root is None:
                self.unmeasured.append(f"plugin {name}: enabled but its files were not found")
                continue
            found.append((name, root))
        return found

    def listing(self, folder, owner, kind):
        """Add one item per skill, command or agent: the text its name and description put in the listing."""
        total = 0
        if not folder.is_dir():
            return 0
        files = sorted(folder.glob("*/SKILL.md")) if kind == "skill" else sorted(folder.rglob("*.md"))
        for f in files:
            text = read(f)
            if text is None:
                continue
            fm = frontmatter(text)
            name = fm.get("name") or (f.parent.name if kind == "skill" else f.stem)
            chars = len(name) + len(fm.get("description", "")) + 4
            total += chars
            if owner.startswith("plugin "):
                action = f"disable the plugin: /plugin disable {owner[7:]} (or set \"{owner[7:]}\": false in enabledPlugins)"
            else:
                action = f"move it out of {self.show(folder)} if you do not use it"
            self.add(f"{kind} listing", f"{owner}: {kind} {name}", chars, action)
        return total

    def listings(self, plugins):
        claude = self.home / ".claude"
        for kind, sub in (("skill", "skills"), ("command", "commands"), ("agent", "agents")):
            self.listing(claude / sub, "user", kind)
            if self.project != self.home:
                self.listing(self.project / ".claude" / sub, "project", kind)
            for name, root in plugins:
                self.listing(root / sub, f"plugin {name}", kind)

    def mcp(self, settings, plugins, tools_seen):
        servers = {}
        user = read_json(self.home / ".claude.json") or {}
        for name in (user.get("mcpServers") or {}):
            servers[name] = "user scope (~/.claude.json)"
        proj = (user.get("projects") or {}).get(str(self.project)) or {}
        for name in (proj.get("mcpServers") or {}):
            servers[name] = "local scope (~/.claude.json, this project)"
        for name in ((read_json(self.project / ".mcp.json") or {}).get("mcpServers") or {}):
            servers[name] = "project scope (.mcp.json)"
        for path, data in settings:
            for name in (data.get("mcpServers") or {}):
                servers[name] = f"settings ({self.show(path)})"
        for pname, root in plugins:
            data = read_json(root / ".mcp.json") or {}
            for name in (data.get("mcpServers") or data):
                if isinstance(name, str):
                    servers[f"plugin_{pname.partition('@')[0]}_{name}"] = f"plugin {pname}"
        lines = []
        for name, where in sorted(servers.items()):
            key = re.sub(r"[^a-z0-9]", "_", name.lower())
            seen = tools_seen.get(key)
            count = f"{len(seen)} tools seen in transcripts (a lower bound)" if seen else "tool count not known"
            lines.append(f"  {name}  [{where}]  {count}")
        return servers, lines

    def hooks_and_style(self, settings, plugins):
        style = None
        for path, data in settings:
            style = data.get("outputStyle", style)
            for event in ("SessionStart", "UserPromptSubmit"):
                for group in (data.get("hooks") or {}).get(event, []) or []:
                    for hook in group.get("hooks", []) if isinstance(group, dict) else []:
                        cmd = str(hook.get("command", ""))[:70]
                        self.unmeasured.append(f"{event} hook in {self.show(path)}: `{cmd}`; its printed output joins the context")
        for name, root in plugins:
            data = read_json(root / "hooks" / "hooks.json") or {}
            for event in ("SessionStart", "UserPromptSubmit"):
                if (data.get("hooks") or {}).get(event):
                    self.unmeasured.append(f"{event} hook from plugin {name}; its printed output joins the context")
        if style and style.lower() not in ("default",):
            dirs = [self.home / ".claude" / "output-styles", self.project / ".claude" / "output-styles"]
            dirs += [root / "output-styles" for _, root in plugins]
            for d in dirs:
                for f in sorted(d.glob("*.md")) if d.is_dir() else []:
                    fm = frontmatter(read(f) or "")
                    if f.stem.lower() == style.lower() or fm.get("name", "").lower() == style.lower():
                        self.add("output style", f"output style {style} ({self.show(f)})", len(read(f) or ""),
                                 "switch back to the default style with /output-style if you do not need it")
                        return
            self.unmeasured.append(f"output style '{style}': file not found (built in, or from a disabled plugin)")

    def duplicates(self, min_chars):
        where = {}
        for label, text in self.instruction_texts.items():
            for para in re.split(r"\n\s*\n", text):
                norm = " ".join(para.split())
                if len(norm) >= min_chars:
                    where.setdefault(norm, set()).add(label.split("  (")[0])
        return [(p, sorted(f)) for p, f in where.items() if len(f) > 1]


def tools_from_transcripts(projects_dir, limit=400):
    """Distinct MCP tool names per server, from the newest transcripts. Reads tool names only."""
    seen = {}
    if not projects_dir.is_dir():
        return seen
    files = sorted(projects_dir.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    for f in files:
        try:
            for line in f.open(encoding="utf-8", errors="replace"):
                if '"mcp__' not in line:
                    continue
                for tool in re.findall(r'"name"\s*:\s*"mcp__([^"]+?)__([^"]+)"', line):
                    key = re.sub(r"[^a-z0-9]", "_", tool[0].lower())
                    seen.setdefault(key, set()).add(tool[1])
        except OSError:
            continue
    return seen


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--home", type=pathlib.Path, default=pathlib.Path.home(), help="home folder (default: yours)")
    parser.add_argument("--project", type=pathlib.Path, default=pathlib.Path.cwd(), help="project folder (default: here)")
    parser.add_argument("--budget", type=int, help="estimated tokens allowed before the first message")
    parser.add_argument("--top", type=int, default=12, help="how many items to rank (default 12)")
    parser.add_argument("--no-transcripts", action="store_true", help="do not read transcripts for MCP tool counts")
    args = parser.parse_args()

    limits, unverified = load_thresholds()
    home, project = args.home.expanduser().resolve(), args.project.expanduser().resolve()
    if not home.is_dir() or not project.is_dir():
        print("RESULT blocked: the home or project folder does not exist")
        return 2
    budget = args.budget if args.budget is not None else int(limits["startup_budget_tokens"])
    a = Audit(home, project, float(limits["chars_per_token"]))
    a.instructions()
    settings = a.settings()
    plugins = a.plugins(settings)
    a.listings(plugins)
    a.hooks_and_style(settings, plugins)
    tools_seen = {} if args.no_transcripts else tools_from_transcripts(home / ".claude" / "projects")
    servers, mcp_lines = a.mcp(settings, plugins, tools_seen)

    print(f"context audit  project: {a.show(project)}  home: {home}")
    print(f"tokens are ESTIMATES: characters / {limits['chars_per_token']:g}")
    if not a.items and not servers:
        print("nothing found: no instruction files, skills, plugins or MCP servers")
        for note in a.unmeasured:
            print(f"NOT MEASURED {note}")
        print("RESULT pass: nothing loads before the first message that this audit can see")
        return 0

    groups = {}
    for item in a.items:
        groups.setdefault(item["kind"], [0, 0])
        groups[item["kind"]][0] += 1
        groups[item["kind"]][1] += item["tokens"]
    total = sum(i["tokens"] for i in a.items)
    print("\nby kind                     items   est. tokens")
    for kind, (n, tok) in sorted(groups.items(), key=lambda kv: -kv[1][1]):
        print(f"  {kind:<24}{n:>7}{tok:>14,}")
    print(f"  {'total':<24}{len(a.items):>7}{total:>14,}")

    owners = {}
    for item in a.items:
        if item["kind"].endswith("listing") and item["label"].startswith("plugin "):
            owner = item["label"].split(":")[0]
            owners[owner] = owners.get(owner, 0) + item["tokens"]
    ranked = sorted(a.items, key=lambda i: -i["tokens"])
    biggest = [{"label": f"{o} (all its skills, commands and agents)", "tokens": t,
                "action": f"disable it: /plugin disable {o[7:]}"} for o, t in owners.items()]
    biggest += [i for i in ranked if not (i["kind"].endswith("listing") and i["label"].startswith("plugin "))]
    biggest.sort(key=lambda i: -i["tokens"])
    print(f"\nbiggest {min(args.top, len(biggest))} (est. tokens, what to switch off)")
    for n, item in enumerate(biggest[:args.top], 1):
        print(f"{n:>3}. {item['tokens']:>8,}  {item['label']}")
        print(f"              -> {item['action']}")

    dups = a.duplicates(int(limits["duplicate_min_chars"]))
    if dups:
        waste = sum(round(len(p) / a.cpt) * (len(f) - 1) for p, f in dups)
        print(f"\nrepeated paragraphs: {len(dups)} appear in more than one instruction file (about {waste:,} est. tokens paid twice)")
        for para, files in dups[:5]:
            print(f"  \"{para[:60]}...\" in {', '.join(files)}")

    print(f"\nMCP servers configured: {len(servers)} (tool schemas not measured; see mcp-trim for which are used)")
    for line in mcp_lines:
        print(line)
    for note in a.unmeasured:
        print(f"NOT MEASURED {note}")
    if unverified:
        print(f"note: thresholds not verified against a primary source: {', '.join(unverified)}")

    print(f"\nestimated startup total {total:,} tokens; budget {budget:,}")
    if total > budget:
        print(f"RESULT fail: about {total:,} estimated tokens load before the first message, over the budget of {budget:,}")
        return 1
    print(f"RESULT pass: about {total:,} estimated tokens load before the first message, within the budget of {budget:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

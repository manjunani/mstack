"""Script test for context-audit: a made-up home folder and project with known sizes.

Known sizes (characters / 4 = estimated tokens):
  ~/.claude/extra.md, imported by ~/.claude/CLAUDE.md: 800 characters -> 200 tokens
  plugin skill "alpha" of bigkit@market: name 5 + description 395 + 4 = 404 characters -> 101 tokens

Usage: context_audit_cases.py <folder>   (a new run folder is made inside it, for example .testrun/lean-context-audit)
"""
import argparse
import sys

import casekit

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("folder")
args = parser.parse_args()
t = casekit.Cases("context-audit cases", args.folder)
AUDIT = casekit.SKILLS / "context-audit" / "scripts" / "audit.py"

home = t.root / "home"
project = home / "code" / "shop"
shared = ("Run the whole test suite before each commit and paste the summary line into the pull request "
          "description so reviewers can see it.")
t.write("home/.claude/CLAUDE.md", f"# Mine\n\n{shared}\n\nSee @~/.claude/extra.md for more.\n")
t.write("home/.claude/extra.md", "y" * 800)
t.write("home/code/shop/CLAUDE.md", f"# Shop\n\n{shared}\n\n```\n@notes/hidden.md\n```\n")
t.write("home/code/shop/notes/hidden.md", "z" * 4000)
t.write("home/code/shop/AGENTS.md", "Agents file for other tools.\n")
t.write(f"home/.claude/projects/{casekit.slug(project)}/memory/MEMORY.md", "- [one note](one.md)\n")
t.write("home/.claude/skills/mine/SKILL.md", "---\nname: mine\ndescription: A small personal skill.\n---\nbody\n")
kit = home / ".claude" / "plugins" / "cache" / "market" / "bigkit" / "1.0.0"
t.write(str(kit.relative_to(t.root) / "skills/alpha/SKILL.md"), "---\nname: alpha\ndescription: " + "d" * 395 + "\n---\nbody\n")
t.write(str(kit.relative_to(t.root) / "skills/beta/SKILL.md"), "---\nname: beta\ndescription: >\n  folded text\n  on two lines\n---\n")
t.json(str(kit.relative_to(t.root) / ".mcp.json"), {"mcpServers": {"docs": {"command": "docs-server"}}})
t.write("home/.claude/plugins/cache/market/offkit/1.0.0/skills/gamma/SKILL.md", "---\nname: gamma\ndescription: off\n---\n")
t.json("home/.claude/plugins/installed_plugins.json", {"version": 2, "plugins": {"bigkit@market": [{"installPath": str(kit)}]}})
t.json("home/.claude/settings.json", {
    "enabledPlugins": {"bigkit@market": True, "offkit@market": False},
    "outputStyle": "Brief",
    "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo start-note"}]}],
              "PreToolUse": [{"hooks": [{"type": "command", "command": "echo not-context"}]}]}})
t.write("home/.claude/output-styles/brief.md", "---\nname: Brief\ndescription: short answers\n---\n" + "s" * 200)
t.json("home/.claude.json", {"mcpServers": {"tracker": {}}, "projects": {str(project): {"mcpServers": {"notes": {}}}}})
t.json("home/code/shop/.mcp.json", {"mcpServers": {"db": {}}})
t.jsonl("home/.claude/projects/other/s1.jsonl", [casekit.turn("m1", 10, 0, 0, 5, tools=["mcp__tracker__list", "mcp__tracker__get"])])

A = ["--home", home, "--project", project]
out = t.run("over a small budget fails and ranks the items", AUDIT, [*A, "--budget", "10"], 1, contains=[
    "200  ~/.claude/extra.md  (imported by ~/.claude/CLAUDE.md)",
    "plugin bigkit@market (all its skills, commands and agents)",
    "-> disable it: /plugin disable bigkit@market",
    "user: skill mine",
    "memory index",
    "whether your client loads AGENTS.md depends on the client",
    "output style Brief",
    "repeated paragraphs: 1 appear in more than one instruction file",
    "NOT MEASURED SessionStart hook",
    "tokens are ESTIMATES",
    "RESULT fail"], absent=["hidden.md", "gamma", "offkit", "not-context"])
t.check("plugin skills are summed per plugin, not listed one by one", "plugin bigkit@market: skill alpha" not in out.stdout)
t.check("plugin total = alpha 101 + beta with its folded description 8", "109  plugin bigkit@market" in out.stdout)
t.run("MCP servers from every source, tool counts from transcripts", AUDIT, [*A, "--budget", "10"], 1, contains=[
    "MCP servers configured: 4", "tracker  [user scope (~/.claude.json)]  2 tools seen in transcripts",
    "notes  [local scope", "db  [project scope (.mcp.json)]", "plugin_bigkit_docs  [plugin bigkit@market]  tool count not known"])
t.run("within a large budget passes", AUDIT, [*A, "--budget", "100000"], 0, contains=["within the budget of 100,000"])
t.run("default budget comes from the thresholds file and is flagged unverified", AUDIT, A, 0,
      contains=["budget 20,000", "thresholds not verified"])
t.run("--no-transcripts leaves tool counts unknown", AUDIT, [*A, "--no-transcripts"], 0, absent=["tools seen"])

empty = t.root / "empty-home"
(empty / "p").mkdir(parents=True)
t.run("an empty setup is a pass with the reason", AUDIT, ["--home", empty, "--project", empty / "p"], 0,
      contains=["RESULT pass: nothing loads"])
t.run("a missing project folder is blocked", AUDIT, ["--home", empty, "--project", empty / "nope"], 2, contains=["RESULT blocked"])

t.json("broken/.claude/settings.json", {"enabledPlugins": {"ghost@market": True}})
t.write("broken/.claude.json", "{ not json")
(t.root / "broken" / "p").mkdir(parents=True)
t.run("broken config and a plugin with no files do not crash", AUDIT, ["--home", t.root / "broken", "--project", t.root / "broken" / "p"], 0,
      contains=["NOT MEASURED plugin ghost@market: enabled but its files were not found"])
sys.exit(t.done())

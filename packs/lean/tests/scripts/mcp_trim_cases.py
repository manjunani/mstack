"""Script test for mcp-trim: a made-up config with five servers and transcripts with known MCP calls.

Configured: tracker (user), notes (local), db (project .mcp.json), wiki (project .mcp.json but disabled for this
project, so not loaded), docs (from enabled plugin bigkit@market, tool prefix plugin_bigkit_docs).
Calls in the period: tracker 3 (one call repeated on a second line with the same id, counted once), db 1,
plugin_bigkit_docs 2, and a connector "web_search" that is not in the config. notes: only an old call (2001).

Usage: mcp_trim_cases.py <folder>   (a new run folder is made inside it, for example .testrun/lean-mcp-trim)
"""
import argparse
import datetime
import sys

import casekit

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("folder")
args = parser.parse_args()
t = casekit.Cases("mcp-trim cases", args.folder)
TRIM = casekit.SKILLS / "mcp-trim" / "scripts" / "mcptrim.py"
turn = casekit.turn

home = t.root / "home"
project = t.root / "work" / "shop"
project.mkdir(parents=True)
t.json("home/.claude.json", {"mcpServers": {"tracker": {}}, "projects": {str(project): {
    "mcpServers": {"notes": {}}, "disabledMcpjsonServers": ["wiki"]}}})
t.json("work/shop/.mcp.json", {"mcpServers": {"db": {}, "wiki": {}}})
t.json("home/.claude/settings.json", {"enabledPlugins": {"bigkit@market": True}})
t.json("home/.claude/plugins/cache/market/bigkit/1.0.0/.mcp.json", {"mcpServers": {"docs": {}}})
now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
OLD = "2001-01-01T00:00:00Z"
same = turn("m1", 1, 0, 0, 1, ts=now, tools=["mcp__tracker__list"])
t.jsonl(f"home/.claude/projects/{casekit.slug(project)}/s1.jsonl", [
    same, same, turn("m2", 1, 0, 0, 1, ts=now, tools=["mcp__tracker__get", "mcp__tracker__get", "mcp__db__query", "Read"]),
    turn("m3", 1, 0, 0, 1, ts=OLD, tools=["mcp__notes__add"])])
t.jsonl("home/.claude/projects/elsewhere/s2.jsonl", [
    turn("m4", 1, 0, 0, 1, ts=now, tools=["mcp__plugin_bigkit_docs__find", "mcp__plugin_bigkit_docs__open", "mcp__web_search__q"])])
A = ["--home", home, "--project", project]

out = t.run("an unused server is a fail with the exact change to make", TRIM, A, 1, contains=[
    "MCP servers loaded for this project: 4", "notes", "claude mcp remove notes -s local",
    "1 of 4 configured servers had no calls in the last 30 days", "seen in transcripts but not in this project's config",
    "web_search"], absent=["wiki"])
t.check("tracker counted 3 calls in 1 session", any(l.startswith("tracker") and " 3 " in l and l.split()[-2] == "1" for l in out.stdout.splitlines()))
t.check("plugin server matched by its tool prefix", any(l.startswith("plugin_bigkit_docs") and " 2 " in l for l in out.stdout.splitlines()))
t.check("the script says it changes nothing", "this script changes nothing" in out.stdout)
t.run("a longer period counts the old call too", TRIM, [*A, "--days", "100000"], 0, contains=["every configured server was called"])
t.run("this project's transcripts only", TRIM, [*A, "--this-project-only"], 1,
      contains=["2 of 4 configured servers had no calls", "/plugin disable bigkit@market"])

bare = t.root / "bare"
(bare / "p").mkdir(parents=True)
t.run("no servers configured is a pass with the reason", TRIM, ["--home", bare, "--project", bare / "p"], 0,
      contains=["no MCP servers are configured"])
t.json("quiet/.claude.json", {"mcpServers": {"tracker": {}}})
(t.root / "quiet" / "p").mkdir(parents=True)
t.run("no transcripts is not verified", TRIM, ["--home", t.root / "quiet", "--project", t.root / "quiet" / "p"], 2,
      contains=["RESULT not verified: no transcripts"])
t.run("a bad period is blocked", TRIM, [*A, "--days", "0"], 2, contains=["RESULT blocked"])
t.write("broken/.claude.json", "{ nope")
(t.root / "broken" / "p").mkdir(parents=True)
t.run("broken config files do not crash", TRIM, ["--home", t.root / "broken", "--project", t.root / "broken" / "p"], 0)
t.check("config files untouched", (home / ".claude.json").read_text().count("tracker") == 1)
sys.exit(t.done())

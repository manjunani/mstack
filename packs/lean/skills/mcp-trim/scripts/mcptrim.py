#!/usr/bin/env python3
"""List the MCP servers Claude Code loads and how often their tools were really called, and print how to turn
off the ones that are not used. Reads only; changes no setting.

Servers come from: ~/.claude.json (user scope, and local scope for --project), the project's .mcp.json,
settings files (~/.claude/settings.json, .claude/settings.json, .claude/settings.local.json) and enabled plugins.
Calls come from transcripts under ~/.claude/projects: every tool use named mcp__<server>__<tool> is counted.
Only tool names and timestamps are read; message text is never printed.

Exit 0 = every configured server was used in the period (or none is configured), 1 = at least one server had no
calls, 2 = not verified (no transcripts in the period) or blocked (bad input).
Examples:
  mcptrim.py                      # last 30 days, every project's transcripts
  mcptrim.py --days 90 --project ~/code/shop
  mcptrim.py --this-project-only
"""
import argparse
import datetime
import json
import pathlib
import re
import sys


def read_json(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def norm(name):
    return re.sub(r"[^a-z0-9]", "_", name.lower())


def configured(home, project):
    """Return {server: (scope, command to turn it off)}."""
    servers = {}
    user = read_json(home / ".claude.json") or {}
    for name in (user.get("mcpServers") or {}):
        servers[name] = ("user", f"claude mcp remove {name} -s user")
    local = (user.get("projects") or {}).get(str(project)) or {}
    for name in (local.get("mcpServers") or {}):
        servers[name] = ("local", f"claude mcp remove {name} -s local   (run inside the project)")
    disabled = set(local.get("disabledMcpjsonServers") or [])
    for name in ((read_json(project / ".mcp.json") or {}).get("mcpServers") or {}):
        if name in disabled:
            continue
        servers[name] = ("project .mcp.json", f'add "{name}" to "disabledMcpjsonServers" in .claude/settings.local.json '
                                              f"(keeps it for teammates), or remove it from .mcp.json")
    settings = [home / ".claude" / "settings.json", project / ".claude" / "settings.json", project / ".claude" / "settings.local.json"]
    enabled = {}
    for path in settings:
        data = read_json(path) or {}
        for name in (data.get("mcpServers") or {}):
            servers[name] = (f"settings {path.name}", f"remove \"{name}\" from mcpServers in {path}")
        for plugin, on in (data.get("enabledPlugins") or {}).items():
            enabled[plugin] = bool(on)
    installed = (read_json(home / ".claude" / "plugins" / "installed_plugins.json") or {}).get("plugins") or {}
    for plugin, on in enabled.items():
        if not on:
            continue
        roots = [pathlib.Path(str(e.get("installPath", ""))) for e in installed.get(plugin, []) if isinstance(e, dict)]
        short, _, market = plugin.partition("@")
        roots += sorted((home / ".claude" / "plugins" / "cache" / market / short).glob("*/"))
        for root in roots:
            data = read_json(root / ".mcp.json")
            if data is None:
                continue
            for name in (data.get("mcpServers") or data):
                if isinstance(name, str):
                    servers[f"plugin_{short}_{name}"] = (f"plugin {plugin}", f"/plugin disable {plugin}   (turns off the whole plugin)")
            break
    return servers


def calls(projects_dir, since, only):
    """Return ({server key: [calls, sessions set, last timestamp]}, transcripts read)."""
    found, files = {}, 0
    folders = [only] if only else [projects_dir]
    for folder in folders:
        if not folder.is_dir():
            continue
        for path in folder.rglob("*.jsonl"):
            if datetime.datetime.fromtimestamp(path.stat().st_mtime, datetime.timezone.utc) < since:
                continue
            files += 1
            seen_ids = set()
            try:
                fh = path.open(encoding="utf-8", errors="replace")
            except OSError:
                continue
            with fh:
                for line in fh:
                    if '"mcp__' not in line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    msg = rec.get("message") if isinstance(rec, dict) and rec.get("type") == "assistant" else None
                    stamp = str(rec.get("timestamp", ""))
                    if not isinstance(msg, dict) or not isinstance(msg.get("content"), list) or stamp[:10] < since.date().isoformat():
                        continue
                    for block in msg["content"]:
                        if not (isinstance(block, dict) and block.get("type") == "tool_use"):
                            continue
                        m = re.match(r"^mcp__(.+?)__(.+)$", str(block.get("name", "")))
                        if not m or block.get("id") in seen_ids:
                            continue
                        seen_ids.add(block.get("id"))
                        entry = found.setdefault(norm(m.group(1)), [0, set(), ""])
                        entry[0] += 1
                        entry[1].add(path.stem)
                        entry[2] = max(entry[2], stamp[:10])
    return found, files


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--home", type=pathlib.Path, default=pathlib.Path.home(), help="home folder (default: yours)")
    parser.add_argument("--project", type=pathlib.Path, default=pathlib.Path.cwd(), help="project folder (default: here)")
    parser.add_argument("--projects-dir", type=pathlib.Path, help="transcript folder (default: <home>/.claude/projects)")
    parser.add_argument("--days", type=int, default=30, help="period to count calls in (default 30)")
    parser.add_argument("--this-project-only", action="store_true", help="count calls in this project's transcripts only")
    args = parser.parse_args()
    if args.days <= 0:
        print("RESULT blocked: --days must be above zero")
        return 2

    home, project = args.home.expanduser().resolve(), args.project.expanduser().resolve()
    projects_dir = (args.projects_dir or home / ".claude" / "projects").expanduser()
    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=args.days)
    only = projects_dir / re.sub(r"[^A-Za-z0-9]", "-", str(project)) if args.this_project_only else None
    servers = configured(home, project)
    used, files = calls(projects_dir, since, only)

    print(f"MCP servers loaded for this project: {len(servers)}   transcripts read: {files} (last {args.days} days)")
    if not servers:
        print("RESULT pass: no MCP servers are configured, nothing to trim")
        return 0
    if files == 0:
        for name, (scope, _) in sorted(servers.items()):
            print(f"  {name}  [{scope}]")
        print(f"RESULT not verified: no transcripts from the last {args.days} days, so use cannot be counted")
        return 2

    idle = []
    print(f"\n{'server':<36}{'scope':<22}{'calls':>7}{'sessions':>10}  last used")
    for name, (scope, off) in sorted(servers.items(), key=lambda kv: -(used.get(norm(kv[0]), [0])[0])):
        n, sessions, last = used.get(norm(name), [0, set(), ""])
        print(f"{name[:35]:<36}{scope[:21]:<22}{n:>7}{len(sessions):>10}  {last or '-'}")
        if n == 0:
            idle.append((name, off))
    extra = sorted(k for k in used if k not in {norm(s) for s in servers})
    if extra:
        print(f"\nseen in transcripts but not in this project's config (a connector, another project, or removed): {', '.join(extra)}")

    if not idle:
        print(f"RESULT pass: every configured server was called in the last {args.days} days")
        return 0
    print(f"\nnot called in {args.days} days; to turn off (run or change it yourself; this script changes nothing):")
    for name, off in idle:
        print(f"  {name}: {off}")
    print(f"RESULT fail: {len(idle)} of {len(servers)} configured servers had no calls in the last {args.days} days")
    return 1


if __name__ == "__main__":
    sys.exit(main())

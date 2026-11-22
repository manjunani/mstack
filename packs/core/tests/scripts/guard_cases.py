"""Feed sample tool calls to the mstack guard hook and compare its decision with the expected one. Runs nothing destructive: the commands are only text passed on standard input."""
import json
import subprocess
import sys

GUARD, CWD = sys.argv[1], sys.argv[2]
CASES = [
    ("deny", "rm -rf docs/old"),
    ("ask", "rm -rf node_modules"),
    ("allow", "rm -rf /tmp/scratch-x"),
    ("deny", "rm -rf ~"),
    ("deny", "rm -rf /"),
    ("ask", 'rm -rf "$DIR/"'),
    ("allow", "rm file.txt"),
    ("deny", "ls -la && rm -rf src"),
    ("deny", "sudo rm -fr src/old"),
    ("ask", "git reset --hard HEAD~2"),
    ("deny", "git push --force origin main"),
    ("ask", "git push --force-with-lease origin feat"),
    ("ask", "git clean -fd"),
    ("ask", 'psql -c "DROP TABLE users"'),
    ("ask", "terraform destroy -auto-approve"),
    ("ask", "railway volume delete x"),
    ("allow", "npm test"),
    ("allow", "git status"),
    ("allow", "git push origin feat"),
    ("allow", "echo done"),
    ("allow", "grep -rn 'reset' docs"),
]
MCP = [("ask", "mcp__railway__delete-volume"), ("allow", "mcp__railway__list-services"), ("ask", "mcp__db__drop_table")]


def decide(event, env=None):
    out = subprocess.run([sys.executable, GUARD], input=json.dumps(event), capture_output=True, text=True, env=env)
    if not out.stdout.strip():
        return "allow", out.returncode
    return json.loads(out.stdout)["hookSpecificOutput"]["permissionDecision"], out.returncode


bad = 0
for want, command in CASES:
    got, code = decide({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": CWD})
    mark = "ok  " if got == want and code == 0 else "BAD "
    bad += mark == "BAD "
    print(f"{mark}{got:6} (want {want:5}) | {command}")
for want, tool in MCP:
    got, code = decide({"tool_name": tool, "tool_input": {}, "cwd": CWD})
    mark = "ok  " if got == want and code == 0 else "BAD "
    bad += mark == "BAD "
    print(f"{mark}{got:6} (want {want:5}) | {tool}")

raw = subprocess.run([sys.executable, GUARD], input="not json", capture_output=True, text=True)
print(f"{'ok  ' if raw.returncode == 0 and not raw.stdout else 'BAD '}fails open on bad input (exit {raw.returncode})")
bad += not (raw.returncode == 0 and not raw.stdout)

import os
off, _ = decide({"tool_name": "Bash", "tool_input": {"command": "rm -rf src"}, "cwd": CWD}, env={**os.environ, "MSTACK_GUARD": "off"})
print(f"{'ok  ' if off == 'allow' else 'BAD '}off switch lets the call through")
bad += off != "allow"
print(f"guard cases: {len(CASES) + len(MCP) + 2} run, {bad} wrong")
sys.exit(1 if bad else 0)

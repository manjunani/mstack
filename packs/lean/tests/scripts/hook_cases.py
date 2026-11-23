"""Feed sample events to the two mstack-lean hooks and compare what they answer with what is expected.

Builds throwaway transcripts and budget files in a NEW folder. Usage: hook_cases.py <new folder>
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys

HOOKS = pathlib.Path(__file__).resolve().parents[2] / "hooks"
parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("folder", type=pathlib.Path)
args = parser.parse_args()
if args.folder.exists():
    sys.exit(f"refusing: {args.folder} already exists")
root = args.folder.resolve()
root.mkdir(parents=True)
state = root / "state"
env = {**os.environ, "CLAUDE_PLUGIN_DATA": str(state)}
env.pop("MSTACK_LEAN", None)
wrong = 0


def transcript(name, context_tokens, agents=0):
    path = root / f"{name}.jsonl"
    rows = [{"type": "user", "message": {"role": "user", "content": "hi"}}]
    for i in range(agents):
        rows.append({"type": "assistant", "message": {"id": f"a{i}", "content": [{"type": "tool_use", "name": "Agent", "input": {}}]}})
    rows.append({"type": "assistant", "message": {"id": "last", "usage": {
        "input_tokens": 10, "cache_read_input_tokens": context_tokens - 110, "cache_creation_input_tokens": 100, "output_tokens": 50}}})
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def run(hook, event, extra_env=None):
    out = subprocess.run([sys.executable, str(HOOKS / hook)], input=json.dumps(event), capture_output=True,
                         text=True, env={**env, **(extra_env or {})}, cwd=root)
    data = json.loads(out.stdout) if out.stdout.strip() else {}
    return out.returncode, data


def check(name, ok):
    global wrong
    wrong += not ok
    print(f"{'ok  ' if ok else 'BAD '}{name}")


# Stop hook
small = transcript("small", 120_000)
code, data = run("session_notice.py", {"session_id": "s1", "transcript_path": str(small)})
check("below the first limit: silent, exit 0", code == 0 and not data)
big = transcript("big", 320_000)
code, data = run("session_notice.py", {"session_id": "s2", "transcript_path": str(big)})
check("crossing 300,000: one notice naming handoff", code == 0 and "handoff" in data.get("systemMessage", ""))
code, data = run("session_notice.py", {"session_id": "s2", "transcript_path": str(big)})
check("same level again: silent", code == 0 and not data)
bigger = transcript("bigger", 530_000)
code, data = run("session_notice.py", {"session_id": "s2", "transcript_path": str(bigger)})
check("next step (500,000+): one more notice", code == 0 and "530,000" in data.get("systemMessage", ""))
code, data = run("session_notice.py", {"session_id": "s3", "transcript_path": str(big)}, {"MSTACK_LEAN": "off"})
check("off switch: silent", code == 0 and not data)
code, data = run("session_notice.py", {"session_id": "s4", "transcript_path": str(root / "missing.jsonl")})
check("missing transcript: silent, fails open", code == 0 and not data)
bad = subprocess.run([sys.executable, str(HOOKS / "session_notice.py")], input="not json", capture_output=True, text=True, env=env)
check("bad input: exit 0, no output", bad.returncode == 0 and not bad.stdout.strip())

# PreToolUse hook on Agent/Task
project = root / "project"
(project / ".mstack").mkdir(parents=True)
few = transcript("few", 50_000, agents=3)
code, data = run("agent_budget.py", {"tool_name": "Agent", "cwd": str(project), "transcript_path": str(few)})
check("no budget, few agents: allow silently", code == 0 and not data)
many = transcript("many", 50_000, agents=9)
code, data = run("agent_budget.py", {"tool_name": "Task", "cwd": str(project), "transcript_path": str(many)})
check("no budget, 10th agent: one warning, still allowed", code == 0 and "budget" in data.get("systemMessage", "")
      and "hookSpecificOutput" not in data)
budget = project / ".mstack" / "fanout-budget.json"
budget.write_text(json.dumps({"limit": 3_000_000, "per_run": 1_000_000, "per_run_source": "test",
                              "created": "2026-01-01T00:00:00+00:00", "recorded_launches": 1}), encoding="utf-8")
code, data = run("agent_budget.py", {"tool_name": "Agent", "cwd": str(project / "src"), "transcript_path": str(few)})
check("budget with room: allowed and recorded", code == 0 and not data
      and json.loads(budget.read_text())["recorded_launches"] == 2)
code, data = run("agent_budget.py", {"tool_name": "Agent", "cwd": str(project), "transcript_path": str(few)})
check("budget reaches the limit exactly: allowed", code == 0 and not data)
code, data = run("agent_budget.py", {"tool_name": "Agent", "cwd": str(project), "transcript_path": str(few)})
decision = data.get("hookSpecificOutput", {}).get("permissionDecision")
check("next launch over the limit: ask, with numbers", decision == "ask" and "4,000,000" in
      data["hookSpecificOutput"]["permissionDecisionReason"] and json.loads(budget.read_text())["recorded_launches"] == 3)
code, data = run("agent_budget.py", {"tool_name": "Bash", "cwd": str(project)})
check("other tools: ignored", code == 0 and not data)
code, data = run("agent_budget.py", {"tool_name": "Agent", "cwd": str(project)}, {"MSTACK_LEAN": "off"})
check("off switch: allowed silently", code == 0 and not data)
budget.write_text("{broken", encoding="utf-8")
code, data = run("agent_budget.py", {"tool_name": "Agent", "cwd": str(project)})
check("broken budget file: fails open", code == 0 and not data)

print(f"hook cases: 15 run, {wrong} wrong")
sys.exit(1 if wrong else 0)

#!/usr/bin/env python3
"""mstack-core guard: a PreToolUse hook that stops destructive actions before they run.

Reads the tool call as JSON on standard input. Answers with a permission decision:
  deny  for removals that should go through safe-delete, and for a few that are never right
  ask   for other destructive commands and for destructive-looking MCP tools; the user decides
  deny  for a file edit outside the folder named by an active scope lock
  (no output) for everything else

It fails open: any error inside this script lets the call through.
Switch it off with the environment variable MSTACK_GUARD=off.
"""
import json
import os
import pathlib
import re
import shlex
import sys
import tempfile

REGENERABLE = {"node_modules", "dist", "build", "target", ".next", ".nuxt", ".turbo", ".cache", "__pycache__",
               ".pytest_cache", ".mypy_cache", ".ruff_cache", ".venv", "venv", "coverage", ".parcel-cache", "DerivedData"}
MCP_VERBS = re.compile(r"(delete|destroy|drop|remove|purge|truncate|wipe|erase|reset|trash)", re.I)
ASK_PATTERNS = [
    (r"\bgit\s+reset\s+--hard\b", "git reset --hard discards uncommitted changes in tracked files"),
    (r"\bgit\s+clean\s+-[a-zA-Z]*f", "git clean deletes untracked files, which git cannot bring back"),
    (r"\bgit\s+(checkout|restore)\s+(--\s+)?\.(\s|$)", "this discards all uncommitted changes in the folder"),
    (r"\bgit\s+branch\s+-D\b", "git branch -D deletes a branch even if it is not merged"),
    (r"\bgit\s+stash\s+(drop|clear)\b", "this deletes stashed work"),
    (r"\bgit\s+push\b.*(--force\b|--force-with-lease\b|\s-f\b)", "a forced push overwrites history on the remote"),
    (r"\bgit\s+filter-(branch|repo)\b", "this rewrites history"),
    (r"\bfind\b.*\s-delete\b", "find -delete removes every match with no trash"),
    (r"\b(drop\s+(table|database|schema)|truncate\s+table?)\b", "this destroys database data"),
    (r"\bdelete\s+from\s+\w+\s*(;|$|\")", "DELETE with no WHERE removes every row"),
    (r"\bterraform\s+destroy\b", "terraform destroy removes infrastructure, and often its backups"),
    (r"\bkubectl\s+delete\b", "kubectl delete removes cluster resources"),
    (r"\bdocker\s+(system|volume)\s+prune\b", "this deletes docker volumes or images"),
    (r"\b(railway|vercel|fly|heroku|supabase)\b.*\b(delete|destroy|remove|rm|down)\b", "this removes a hosted resource"),
    (r"\bgh\s+repo\s+delete\b", "this deletes a GitHub repository"),
    (r"\bdd\s+.*\bof=/dev/", "dd to a device overwrites it"),
    (r"\bmkfs\b|\bdiskutil\s+erase", "this erases a disk"),
]


def answer(decision, reason):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision,
                                             "permissionDecisionReason": "mstack guard: " + reason}}))
    sys.exit(0)


def segments(command):
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return []
    out, current = [], []
    for token in tokens:
        if set(token) <= set(";&|"):
            if current:
                out.append(current)
            current = []
        else:
            current.append(token)
    if current:
        out.append(current)
    return out


def classify_target(raw, cwd):
    """temp, regenerable, catastrophic, unknown or other."""
    if raw in ("/", "/*", "~", "~/", "~/*", "$HOME", "$HOME/", "$HOME/*", "..", "../", "*", ".", "./"):
        return "catastrophic"
    if "$" in raw or "`" in raw:
        return "unknown"
    text = raw.split("*")[0].rstrip("/") or raw
    path = pathlib.Path(text).expanduser()
    path = path if path.is_absolute() else cwd / path
    try:
        path = path.resolve()
    except OSError:
        return "other"
    temps = {pathlib.Path(tempfile.gettempdir()).resolve(), pathlib.Path("/tmp").resolve(), pathlib.Path("/private/tmp")}
    if any(t == path or t in path.parents for t in temps):
        return "temp"
    if path == pathlib.Path.home().resolve() or path == pathlib.Path(path.anchor):
        return "catastrophic"
    if path.name in REGENERABLE or any(part in REGENERABLE for part in path.parts[len(cwd.parts):]) and cwd in path.parents:
        return "regenerable"
    return "other"


def check_bash(command, cwd):
    for words in segments(command):
        while words and (words[0] in ("sudo", "command", "env", "time", "nohup") or re.match(r"^\w+=", words[0])):
            words = words[1:]
        if not words or pathlib.Path(words[0]).name != "rm":
            continue
        flags = [w for w in words[1:] if w.startswith("-") and w != "--"]
        targets = [w for w in words[1:] if not w.startswith("-")]
        recursive = any(f == "--recursive" or (not f.startswith("--") and ("r" in f or "R" in f)) for f in flags)
        if not recursive:
            continue
        kinds = {classify_target(t, cwd) for t in targets}
        if "catastrophic" in kinds:
            answer("deny", "this would remove the home folder, the file system root or the whole current folder. It is never run.")
        if kinds <= {"temp"}:
            continue
        if "unknown" in kinds:
            answer("ask", "the path comes from a variable. If the variable is empty this removes far more than intended. "
                          "Check the value first, or use safe-delete: manifest.py plan <real path>.")
        if kinds <= {"temp", "regenerable"}:
            answer("ask", "recursive delete of a folder that can be rebuilt (" + ", ".join(targets) + "). Allow if a rebuild is acceptable.")
        answer("deny", "recursive delete has no undo. Use the safe-delete skill instead: "
                       "`manifest.py plan " + " ".join(shlex.quote(t) for t in targets) + "` lists what would go and what refers to it, "
                       "then `manifest.py apply <id>` moves it to a trash folder that `undo` restores.")
    lowered = command.lower()
    for pattern, reason in ASK_PATTERNS:
        if re.search(pattern, lowered):
            if re.search(r"git\s+push\b.*(--force\b|\s-f\b)(?!-with-lease)", lowered) and re.search(r"\b(main|master)\b", lowered):
                answer("deny", "forced push to the default branch overwrites shared history. It is never run by an agent.")
            answer("ask", reason + ". Before allowing: is there a backup or another copy, and what depends on this?")


def check_scope(raw, cwd):
    """Deny an edit outside the folder named in .mstack/scope-lock.json, if a lock is set."""
    project = next((p for p in (cwd, *cwd.parents) if (p / ".mstack" / "scope-lock.json").exists()), None)
    if project is None or not raw:
        return
    lock = json.loads((project / ".mstack" / "scope-lock.json").read_text(encoding="utf-8"))
    root = pathlib.Path(lock["root"])
    path = pathlib.Path(raw).expanduser()
    path = (path if path.is_absolute() else cwd / path).resolve()
    temps = {pathlib.Path(tempfile.gettempdir()).resolve(), pathlib.Path("/tmp").resolve()}
    inside = path == root or root in path.parents or (project / ".mstack") in path.parents
    if inside or any(t == path or t in path.parents for t in temps):
        return
    answer("deny", f"scope lock: edits are limited to {root}, and {path} is outside it. "
                   "If this file has to change, stop and tell the user which file and why; only the user releases the lock.")


def main():
    if os.environ.get("MSTACK_GUARD", "").lower() == "off":
        return
    event = json.load(sys.stdin)
    tool = event.get("tool_name", "")
    payload = event.get("tool_input") or {}
    cwd = pathlib.Path(event.get("cwd") or os.getcwd()).resolve()
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        check_scope(str(payload.get("file_path") or payload.get("notebook_path") or ""), cwd)
    elif tool == "Bash":
        check_bash(str(payload.get("command", "")), cwd)
    elif tool.startswith("mcp__"):
        name = tool.split("__")[-1]
        if MCP_VERBS.search(name):
            answer("ask", f"the tool '{name}' looks destructive and a command guard cannot see what it removes. "
                          "Before allowing: what exactly will it remove, is there a backup, and does the backup live outside the thing being removed?")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:  # fail open: a broken guard must not block work
        pass
    sys.exit(0)

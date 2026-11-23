#!/usr/bin/env python3
"""mstack-lean Stop hook: says once, in one line, when a session has grown expensive to continue.

Every new message re-reads the whole conversation. After each reply this hook reads the latest usage
in the session transcript. When the context the next message will re-read crosses the first limit
(default 300,000 tokens), and again at each further step (default 200,000), it prints one line that
suggests handing off to a fresh session. Below the limit it is silent. It never blocks anything.

Limits: limits.json beside this file. Off switch: MSTACK_LEAN=off. Any error lets the reply through
with no message.
"""
import json
import os
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent


def limits():
    data = json.loads((HERE / "limits.json").read_text(encoding="utf-8"))
    return int(data["session_first_notice_tokens"]), int(data["session_notice_step_tokens"])


def latest_context(transcript):
    """Tokens the next message will re-read: input plus cache read plus cache write of the last reply."""
    last = None
    with open(transcript, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if '"usage"' not in line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            usage = (row.get("message") or {}).get("usage")
            if row.get("type") == "assistant" and isinstance(usage, dict):
                last = usage
    if not last:
        return None
    return sum(int(last.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))


def state_file(session):
    base = os.environ.get("CLAUDE_PLUGIN_DATA") or tempfile.gettempdir()
    folder = pathlib.Path(base) / "mstack-lean"
    folder.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in session if c.isalnum() or c in "-_")[:80] or "unknown"
    return folder / f"session-{safe}.json"


def main():
    if os.environ.get("MSTACK_LEAN", "").lower() == "off":
        return
    event = json.load(sys.stdin)
    transcript = event.get("transcript_path")
    if not transcript or not os.path.exists(transcript):
        return
    tokens = latest_context(transcript)
    if tokens is None:
        return
    first, step = limits()
    if tokens < first:
        return
    level = 1 + (tokens - first) // step  # 1 at the first limit, 2 one step later, and so on
    path = state_file(str(event.get("session_id") or transcript))
    shown = 0
    if path.exists():
        shown = int(json.loads(path.read_text(encoding="utf-8")).get("level", 0))
    if level <= shown:
        return
    path.write_text(json.dumps({"level": level, "tokens": tokens}), encoding="utf-8")
    message = (f"mstack-lean: each new message now re-reads about {tokens:,} tokens of this conversation. "
               "Consider a fresh session: the handoff skill (mstack-core) writes the state to one file to continue from.")
    print(json.dumps({"systemMessage": message}))


if __name__ == "__main__":
    try:
        main()
    except Exception:  # fail open: a broken hook must never stop the conversation
        pass
    sys.exit(0)

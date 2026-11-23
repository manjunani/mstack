"""A small stdio MCP server for a notes app. Standard library only; it reads and writes notes.json here."""
import json
import pathlib
import sys

NOTES = pathlib.Path("notes.json")

TOOLS = [
    {"name": "list_notes", "description": "List the titles of all saved notes. Use before reading one.",
     "inputSchema": {"type": "object", "properties": {}}, "annotations": {"readOnlyHint": True}},
    {"name": "read_note", "description": "Return the text of one note by its title.",
     "inputSchema": {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]},
     "annotations": {"readOnlyHint": True}},
    {"name": "count_words", "description": "Count the words in a note.",
     "inputSchema": {"type": "object", "properties": {"title": {"type": "text"}}, "required": ["name"]},
     "annotations": {"readOnlyHint": True}},
    {"name": "delete_note", "description": "Delete a note by its title. This cannot be undone.",
     "inputSchema": {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]}},
]


def load():
    return json.loads(NOTES.read_text()) if NOTES.exists() else {"Shopping": "eggs, rice, lemons"}


def call(name, args):
    notes = load()
    if name == "list_notes":
        return "\n".join(notes)
    if name == "read_note":
        return notes.get(args.get("title"), "no such note")
    if name == "count_words":
        return str(len(notes.get(args.get("title"), "").split()))
    if name == "delete_note":
        notes.pop(args.get("title"), None)
        NOTES.write_text(json.dumps(notes))
        return "deleted"
    raise KeyError(name)


def reply(msg_id, result=None, error=None):
    out = {"jsonrpc": "2.0", "id": msg_id}
    out["error" if error else "result"] = error or result
    sys.stdout.write(json.dumps(out) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    msg = json.loads(line)
    method, msg_id = msg.get("method"), msg.get("id")
    if msg_id is None:
        continue
    if method == "initialize":
        reply(msg_id, {"protocolVersion": msg["params"].get("protocolVersion", "2025-06-18"),
                       "capabilities": {"tools": {}}, "serverInfo": {"name": "notes", "version": "0.3.0"}})
    elif method == "tools/list":
        reply(msg_id, {"tools": TOOLS})
    elif method == "tools/call":
        try:
            text = call(msg["params"]["name"], msg["params"].get("arguments", {}))
            reply(msg_id, {"content": [{"type": "text", "text": text}]})
        except KeyError:
            reply(msg_id, error={"code": -32602, "message": "unknown tool"})
    else:
        reply(msg_id, error={"code": -32601, "message": "method not found"})

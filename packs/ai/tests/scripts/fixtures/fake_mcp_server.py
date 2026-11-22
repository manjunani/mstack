"""A tiny fake MCP server for the mcp-check script test. It speaks JSON-RPC over stdin and stdout.

It is a test fixture, not a real server: its tools do arithmetic and echo text, and the tool called
delete_everything deletes nothing. Every tools/call it receives is appended to the file named by --log,
so the test can prove which tools were called.

--mode chooses a behaviour: good, bad-schema, wrong-output, duplicate, crash, silent, chatty, paged, old, no-tools-cap
"""
import argparse
import json
import sys
import time

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--mode", default="good")
parser.add_argument("--log", required=True)
args = parser.parse_args()

READ = {"readOnlyHint": True}
ADD = {"name": "add", "description": "Add two numbers. Use for sums.", "annotations": READ,
       "inputSchema": {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}, "required": ["a", "b"]},
       "outputSchema": {"type": "object", "properties": {"sum": {"type": "number"}}, "required": ["sum"]}}
ECHO = {"name": "echo", "description": "Repeat a text.", "annotations": READ,
        "inputSchema": {"type": "object", "properties": {"text": {"type": "string", "minLength": 1}, "style": {"type": "string", "enum": ["plain", "upper"]}},
                        "required": ["text"]}}
WIPE = {"name": "delete_everything", "description": "Test stub. Deletes nothing.", "annotations": {"destructiveHint": True},
        "inputSchema": {"type": "object", "properties": {}}}
TOOLS = [ADD, ECHO, WIPE]
if args.mode == "bad-schema":
    TOOLS = [
        {"name": "lookup", "description": "x", "inputSchema": {"type": "object", "properties": {"id": {"type": "strng"}}, "required": ["id", "region"]}},
        {"name": "pick", "description": "x", "inputSchema": {"type": "object", "properties": {"colour": {"type": "string", "enum": []}, "size": {"type": "integer", "enum": [1, "two"]}}}},
        {"name": "list_all", "description": "x", "inputSchema": {"type": "array"}},
    ]
if args.mode == "duplicate":
    TOOLS = [ADD, ECHO, dict(ECHO)]


def out(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def call(name, arguments):
    with open(args.log, "a", encoding="utf-8") as handle:
        handle.write(name + "\n")
    if name == "add":
        if not all(isinstance(arguments.get(k), (int, float)) for k in ("a", "b")):
            return {"content": [{"type": "text", "text": "a and b have to be numbers"}], "isError": True}
        total = arguments["a"] + arguments["b"]
        structured = {"sum": "three"} if args.mode == "wrong-output" else {"sum": total}
        return {"content": [{"type": "text", "text": str(total)}], "structuredContent": structured}
    if name == "echo":
        text = arguments.get("text", "")
        return {"content": [{"type": "text", "text": text.upper() if arguments.get("style") == "upper" else text}]}
    if name == "delete_everything":
        return {"content": [{"type": "text", "text": "stub: nothing was deleted"}]}
    return None


if args.mode == "crash":
    sys.stderr.write("fake server: cannot open the config file\n")
    sys.exit(3)
if args.mode == "chatty":
    print("starting up, loading 3 tools")
    sys.stdout.flush()
for line in sys.stdin:
    if not line.strip():
        continue
    message = json.loads(line)
    method, ident = message.get("method"), message.get("id")
    if args.mode == "silent":
        time.sleep(30)
        continue
    if ident is None:
        continue
    if method == "initialize":
        capabilities = {} if args.mode == "no-tools-cap" else {"tools": {}}
        version = "2024-11-05" if args.mode == "old" else message["params"]["protocolVersion"]
        out({"jsonrpc": "2.0", "method": "notifications/message", "params": {"level": "info", "data": "hello"}})
        out({"jsonrpc": "2.0", "id": "srv-1", "method": "ping"})
        out({"jsonrpc": "2.0", "id": ident, "result": {"protocolVersion": version, "capabilities": capabilities,
                                                    "serverInfo": {"name": "fake-server", "version": "0.0.1"}}})
    elif method == "tools/list":
        if args.mode == "paged":
            cursor = (message.get("params") or {}).get("cursor")
            page = TOOLS[:2] if not cursor else TOOLS[2:]
            result = {"tools": page, **({"nextCursor": "page-2"} if not cursor else {})}
        else:
            result = {"tools": TOOLS}
        out({"jsonrpc": "2.0", "id": ident, "result": result})
    elif method == "tools/call":
        params = message.get("params") or {}
        result = call(params.get("name"), params.get("arguments") or {})
        if result is None:
            out({"jsonrpc": "2.0", "id": ident, "error": {"code": -32602, "message": "unknown tool"}})
        else:
            out({"jsonrpc": "2.0", "id": ident, "result": result})
    else:
        out({"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": "method not found"}})

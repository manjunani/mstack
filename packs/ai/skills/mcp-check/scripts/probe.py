#!/usr/bin/env python3
"""Prove that a stdio MCP server starts, lists its tools, and answers the calls you name as its schemas say.

  probe.py --server "<command that starts the server>" [--call NAME JSON] ... [--calls-file FILE]

What it does, in order:
  1. Starts the command (no shell) and speaks JSON-RPC 2.0 over stdin and stdout, one message per line.
  2. Sends initialize, checks the answer, sends notifications/initialized.
  3. Sends tools/list (following nextCursor) and checks every tool: a name, no duplicate names, and an input
     schema that is well formed. Schema keywords checked: type, properties, required, enum, items.
     Other keywords are listed as "not checked".
  4. Calls ONLY the tools named with --call or in --calls-file, with the arguments given. The arguments are
     checked against the tool's input schema first. The answer must hold content, must not be an error, and
     must fit the tool's output schema when the tool declares one.

A tool the server does not mark readOnlyHint: true is called only with --allow-write. A tool that was not
named is never called.

--calls-file is a JSON list: [{"tool": "add", "arguments": {"a": 1, "b": 2}, "expect_contains": "3"},
                              {"tool": "add", "arguments": {"a": "x"}, "expect_error": true}]

The server's stderr is saved to .mstack/mcp-check/server-stderr.log in the current folder.

Exit codes: 0 = pass: every named call answered correctly and every schema is well formed
            1 = fail: a handshake, schema or call check failed
            2 = not verified (no tool was called, or a call was held back) or blocked (the server did not start)
The last line printed is the result.
"""
import argparse
import json
import pathlib
import queue
import shlex
import subprocess
import sys
import threading

STATE = pathlib.Path(".mstack") / "mcp-check"
PROTOCOL = pathlib.Path(__file__).resolve().parent.parent / "references" / "protocol.json"
TYPES = {"string", "number", "integer", "boolean", "object", "array", "null"}
CHECKED = {"type", "properties", "required", "enum", "items"}
ANNOTATION = {"description", "title", "default", "examples", "$schema", "$id", "$comment", "deprecated", "readOnly", "writeOnly"}


def end(state, why=""):
    why = " ".join(str(why).split())  # the result stays on one line, whatever text it quotes
    print(f"RESULT {state}" + (f": {why}" if why else ""))
    return {"pass": 0, "fail": 1}.get(state, 2)


def type_ok(value, name):
    if name == "string":
        return isinstance(value, str)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "integer":
        return (isinstance(value, int) and not isinstance(value, bool)) or (isinstance(value, float) and value.is_integer())
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "null":
        return value is None
    return False


def schema_problems(schema, where, problems, unchecked):
    """Check that a schema is well formed, for the keywords this script knows."""
    if isinstance(schema, bool):
        return
    if not isinstance(schema, dict):
        problems.append(f"{where}: a schema has to be an object, found {type(schema).__name__}")
        return
    unchecked.update(k for k in schema if k not in CHECKED and k not in ANNOTATION)
    kinds = schema.get("type")
    if "type" in schema:
        listed = kinds if isinstance(kinds, list) else [kinds]
        if not listed or any(not isinstance(k, str) or k not in TYPES for k in listed):
            problems.append(f"{where}: type {json.dumps(kinds)} is not a JSON Schema type")
            kinds = None
        elif len(set(listed)) != len(listed):
            problems.append(f"{where}: type lists the same name twice")
    props = schema.get("properties")
    if "properties" in schema:
        if not isinstance(props, dict):
            problems.append(f"{where}: properties has to be an object")
            props = None
        else:
            for key, sub in props.items():
                schema_problems(sub, f"{where}.{key}", problems, unchecked)
    if "required" in schema:
        required = schema["required"]
        if not isinstance(required, list) or any(not isinstance(r, str) for r in required):
            problems.append(f"{where}: required has to be a list of names")
        else:
            if len(set(required)) != len(required):
                problems.append(f"{where}: required names a property twice")
            for name in required:
                if not isinstance(props, dict) or name not in props:
                    problems.append(f"{where}: required names '{name}', which is not in properties")
    if "enum" in schema:
        values = schema["enum"]
        if not isinstance(values, list) or not values:
            problems.append(f"{where}: enum has to be a list with at least one value")
        else:
            if len({json.dumps(v, sort_keys=True) for v in values}) != len(values):
                problems.append(f"{where}: enum holds the same value twice")
            if kinds:
                listed = kinds if isinstance(kinds, list) else [kinds]
                for v in values:
                    if not any(type_ok(v, k) for k in listed):
                        problems.append(f"{where}: enum value {json.dumps(v)} does not have the declared type {json.dumps(kinds)}")
    if "items" in schema:
        items = schema["items"]
        for i, sub in enumerate(items if isinstance(items, list) else [items]):
            schema_problems(sub, f"{where}[{i if isinstance(items, list) else ''}]", problems, unchecked)


def value_problems(value, schema, where, problems):
    """Check a value against a schema, for the same keywords."""
    if not isinstance(schema, dict):
        if schema is False:
            problems.append(f"{where}: the schema allows no value here")
        return
    kinds = schema.get("type")
    if kinds is not None:
        listed = kinds if isinstance(kinds, list) else [kinds]
        if not any(type_ok(value, k) for k in listed):
            problems.append(f"{where}: {json.dumps(value)[:60]} is not of type {json.dumps(kinds)}")
            return
    if isinstance(schema.get("enum"), list) and value not in schema["enum"]:
        problems.append(f"{where}: {json.dumps(value)[:60]} is not one of {json.dumps(schema['enum'])[:120]}")
    if isinstance(value, dict):
        for name in schema.get("required") or []:
            if name not in value:
                problems.append(f"{where}: required property '{name}' is absent")
        for key, sub in (schema.get("properties") or {}).items():
            if key in value:
                value_problems(value[key], sub, f"{where}.{key}", problems)
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for i, item in enumerate(value):
            value_problems(item, schema["items"], f"{where}[{i}]", problems)


class Server:
    """One running server process and the JSON-RPC conversation with it."""

    def __init__(self, command, cwd, timeout, stderr_file):
        self.timeout = timeout
        self.next_id = 0
        self.garbage = []
        self.lines = queue.Queue()
        self.proc = subprocess.Popen(command, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr_file,
                                     text=True, encoding="utf-8", errors="replace", bufsize=1)
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        for line in self.proc.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def send(self, message):
        try:
            self.proc.stdin.write(json.dumps(message) + "\n")
            self.proc.stdin.flush()
            return True
        except (BrokenPipeError, OSError, ValueError):
            return False

    def request(self, method, params=None):
        """Return (answer, problem). answer is the JSON-RPC message with our id, or None."""
        self.next_id += 1
        ident = self.next_id
        message = {"jsonrpc": "2.0", "id": ident, "method": method}
        if params is not None:
            message["params"] = params
        if not self.send(message):
            return None, "the server closed its input"
        while True:
            try:
                line = self.lines.get(timeout=self.timeout)
            except queue.Empty:
                return None, f"no answer to {method} within {self.timeout:g} seconds"
            if line is None:
                return None, f"the server exited (code {self.proc.wait()}) before answering {method}"
            if not line.strip():
                continue
            try:
                got = json.loads(line)
            except ValueError:
                self.garbage.append(line.strip()[:120])
                continue
            if not isinstance(got, dict):
                self.garbage.append(line.strip()[:120])
                continue
            if got.get("id") == ident and "method" not in got:
                return got, None
            if "method" in got and "id" in got:  # a request from the server to us
                if got["method"] == "ping":
                    self.send({"jsonrpc": "2.0", "id": got["id"], "result": {}})
                else:
                    self.send({"jsonrpc": "2.0", "id": got["id"], "error": {"code": -32601, "message": "this probe does not offer " + str(got["method"])}})
            # anything else is a notification: nothing to do

    def stop(self):
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        for action in (None, self.proc.terminate, self.proc.kill):
            if action:
                action()
            try:
                self.proc.wait(timeout=2)
                return
            except subprocess.TimeoutExpired:
                continue


def read_calls(args):
    calls = []
    for name, raw in args.call or []:
        try:
            arguments = json.loads(raw)
        except ValueError as exc:
            raise ValueError(f"--call {name}: the arguments are not JSON ({exc})")
        calls.append({"tool": name, "arguments": arguments})
    if args.calls_file:
        try:
            listed = json.loads(pathlib.Path(args.calls_file).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"--calls-file {args.calls_file} cannot be read ({exc})")
        if not isinstance(listed, list) or any(not isinstance(c, dict) or not isinstance(c.get("tool"), str) for c in listed):
            raise ValueError("--calls-file has to be a JSON list of objects with a 'tool' name")
        calls += [dict(c, arguments=c.get("arguments", {})) for c in listed]
    for call in calls:
        if not isinstance(call["arguments"], dict):
            raise ValueError(f"the arguments for {call['tool']} have to be a JSON object")
    return calls


def answer_text(result):
    parts = [c.get("text", "") for c in result.get("content") or [] if isinstance(c, dict) and isinstance(c.get("text"), str)]
    if "structuredContent" in result:
        parts.append(json.dumps(result["structuredContent"], sort_keys=True))
    return "\n".join(parts)


def check_call(server, call, tool, allow_write):
    """Return (state, detail) where state is ok, FAIL or HELD."""
    annotations = tool.get("annotations") if isinstance(tool.get("annotations"), dict) else {}
    if annotations.get("readOnlyHint") is not True and not allow_write:
        return "HELD", "the server does not mark this tool read-only; it may change something. Ask the user, then add --allow-write"
    expect_error = call.get("expect_error") is True
    if not expect_error:
        misfit = []
        value_problems(call["arguments"], tool.get("inputSchema", {}), "arguments", misfit)
        if misfit:
            return "HELD", "the arguments given do not fit the tool's input schema (" + "; ".join(misfit[:4]) + "); correct them, or set expect_error to test a refusal"
    answer, problem = server.request("tools/call", {"name": call["tool"], "arguments": call["arguments"]})
    if problem:
        return "FAIL", problem
    if "error" in answer:
        text = json.dumps(answer["error"])[:200]
        return ("ok", "refused as expected: " + text) if expect_error else ("FAIL", "the call returned a JSON-RPC error: " + text)
    result = answer.get("result")
    if not isinstance(result, dict):
        return "FAIL", "the answer has no result object"
    content = result.get("content")
    structured = "structuredContent" in result
    if content is None and not structured:
        return "FAIL", "the result has neither content nor structuredContent"
    if content is not None:
        if not isinstance(content, list):
            return "FAIL", "content is not a list"
        for i, item in enumerate(content):
            if not isinstance(item, dict) or not isinstance(item.get("type"), str):
                return "FAIL", f"content[{i}] has no type"
            if item["type"] == "text" and not isinstance(item.get("text"), str):
                return "FAIL", f"content[{i}] is a text item without text"
    text = answer_text(result)
    if result.get("isError") is True:
        return ("ok", "refused as expected: " + text[:160]) if expect_error else ("FAIL", "the tool reported an error: " + text[:200])
    if expect_error:
        return "FAIL", "an error was expected, but the call succeeded: " + text[:160]
    if not text.strip() and not any(isinstance(c, dict) and c.get("type") != "text" for c in content or []):
        return "FAIL", "the answer is empty"
    if isinstance(tool.get("outputSchema"), dict):
        if not structured:
            return "FAIL", "the tool declares an output schema but the result has no structuredContent"
        misfit = []
        value_problems(result["structuredContent"], tool["outputSchema"], "structuredContent", misfit)
        if misfit:
            return "FAIL", "the result does not fit the tool's output schema: " + "; ".join(misfit[:4])
    wanted = call.get("expect_contains")
    if wanted is not None and str(wanted) not in text:
        return "FAIL", f"the answer does not contain {str(wanted)!r}: " + text[:160]
    return "ok", "answered: " + " ".join(text.split())[:120]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--server", required=True, help="the command that starts the server, in one quoted string")
    parser.add_argument("--cwd", help="folder to start the server in (default: the current folder)")
    parser.add_argument("--call", nargs=2, action="append", metavar=("NAME", "JSON"), help="call this tool with these arguments; repeat for more calls")
    parser.add_argument("--calls-file", help="a JSON list of calls, each with tool, arguments, and optionally expect_contains or expect_error")
    parser.add_argument("--allow-write", action="store_true", help="also call named tools that the server does not mark read-only")
    parser.add_argument("--timeout", type=float, default=10.0, help="seconds to wait for each answer (default %(default)s)")
    parser.add_argument("--protocol-version", help="protocol revision to offer (default: the value in references/protocol.json)")
    args = parser.parse_args()

    try:
        calls = read_calls(args)
        command = shlex.split(args.server)
        if not command:
            raise ValueError("--server is empty")
    except ValueError as exc:
        return end("blocked", str(exc))
    version = args.protocol_version
    if not version:
        try:
            entry = json.loads(PROTOCOL.read_text(encoding="utf-8"))["protocol_version"]
        except (OSError, ValueError, KeyError) as exc:
            return end("blocked", f"{PROTOCOL} cannot be used ({exc}); pass --protocol-version")
        version = entry["value"]
        if not entry.get("verified"):
            print(f"note: protocol revision {version} comes from {PROTOCOL.name} and was written from memory, not checked against the specification.")

    STATE.mkdir(parents=True, exist_ok=True)
    ignore = STATE.parent / ".gitignore"
    if "mcp-check/" not in (ignore.read_text(encoding="utf-8") if ignore.exists() else ""):
        with ignore.open("a", encoding="utf-8") as handle:
            handle.write("mcp-check/\n")
    log_path = STATE / "server-stderr.log"

    def stderr_tail():
        try:
            lines = log_path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
        except OSError:
            return ""
        return (" Last stderr line: " + lines[-1][:200]) if lines else ""

    print(f"server command: {command}")
    with log_path.open("w", encoding="utf-8") as log:
        try:
            server = Server(command, args.cwd, args.timeout, log)
        except (OSError, ValueError) as exc:
            return end("blocked", f"the server command could not be started ({exc}). Check the command and that its runtime is installed")
        try:
            return converse(server, calls, args, version, log_path, stderr_tail)
        finally:
            server.stop()


def converse(server, calls, args, version, log_path, stderr_tail):
    failures = []

    answer, problem = server.request("initialize", {"protocolVersion": version, "capabilities": {},
                                                    "clientInfo": {"name": "mstack-mcp-check", "version": "0.1.0"}})
    if problem:
        if "exited" in problem or "closed its input" in problem:
            return end("blocked", f"{problem}. stderr is in {log_path}.{stderr_tail()}")
        return end("fail", f"{problem}. stderr is in {log_path}.{stderr_tail()}")
    if "error" in answer or not isinstance(answer.get("result"), dict):
        return end("fail", "initialize was refused: " + json.dumps(answer.get("error", answer))[:200])
    info = answer["result"]
    server_info = info.get("serverInfo") if isinstance(info.get("serverInfo"), dict) else {}
    print(f"initialize: server {server_info.get('name', '(no name)')} {server_info.get('version', '')}, protocol {info.get('protocolVersion', '(none)')}")
    if not isinstance(info.get("protocolVersion"), str):
        failures.append("initialize: the answer has no protocolVersion")
    elif info["protocolVersion"] != version:
        print(f"note: the probe offered {version}; the server speaks {info['protocolVersion']}. The checks below use only tools/list and tools/call.")
    if not isinstance(info.get("capabilities"), dict):
        failures.append("initialize: the answer has no capabilities object")
    elif "tools" not in info["capabilities"]:
        failures.append("initialize: the server does not declare the tools capability")
    if not server_info.get("name"):
        failures.append("initialize: the answer has no serverInfo.name")
    server.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    tools, cursor, pages = [], None, 0
    while True:
        answer, problem = server.request("tools/list", {"cursor": cursor} if cursor else {})
        pages += 1
        if problem or "error" in answer or not isinstance(answer.get("result"), dict) or not isinstance(answer["result"].get("tools"), list):
            why = problem or json.dumps(answer.get("error", answer))[:200]
            for line in failures:
                print("FAIL " + line)
            return end("fail", f"tools/list did not return a tool list: {why}.{stderr_tail()}")
        tools += answer["result"]["tools"]
        cursor = answer["result"].get("nextCursor")
        if not cursor:
            break
        if pages >= 50:
            failures.append("tools/list: more than 50 pages; stopped following nextCursor")
            break
    print(f"tools/list: {len(tools)} tools in {pages} page{'s' if pages != 1 else ''}")
    if not tools:
        failures.append("tools/list: the server lists no tools")

    by_name, unchecked = {}, set()
    for index, tool in enumerate(tools):
        name = tool.get("name") if isinstance(tool, dict) else None
        label = name if isinstance(name, str) and name else f"(tool {index + 1})"
        problems = []
        if not isinstance(tool, dict):
            failures.append(f"{label}: not an object")
            continue
        if not isinstance(name, str) or not name:
            problems.append("no name")
        elif name in by_name:
            problems.append("the name is used by more than one tool")
        else:
            by_name[name] = tool
        schema = tool.get("inputSchema")
        if not isinstance(schema, dict):
            problems.append("no inputSchema object")
        else:
            if schema.get("type") != "object":
                problems.append(f"inputSchema.type is {json.dumps(schema.get('type'))}; a tool's input has to be an object")
            schema_problems(schema, "inputSchema", problems, unchecked)
        if "outputSchema" in tool:
            schema_problems(tool["outputSchema"], "outputSchema", problems, unchecked)
        notes = []
        if not isinstance(tool.get("description"), str) or not tool["description"].strip():
            notes.append("no description")
        mode = "read-only" if isinstance(tool.get("annotations"), dict) and tool["annotations"].get("readOnlyHint") is True else "not marked read-only"
        if problems:
            failures += [f"{label}: {p}" for p in problems]
            print(f"TOOL {label}: schema NOT well formed ({len(problems)} problems); {mode}")
        else:
            print(f"TOOL {label}: schema well formed; {mode}" + ("; " + ", ".join(notes) if notes else ""))
    if unchecked:
        print(f"not checked: schema keywords outside this script's subset: {', '.join(sorted(unchecked))}")

    called, held = set(), []
    for call in calls:
        name = call["tool"]
        if name not in by_name:
            failures.append(f"call {name}: the server lists no tool with this name")
            continue
        state, detail = check_call(server, call, by_name[name], args.allow_write)
        detail = " ".join(detail.split())
        print(f"CALL {name} {json.dumps(call['arguments'])[:80]}: {state}: {detail}")
        if state == "FAIL":
            failures.append(f"call {name}: {detail}")
        elif state == "HELD":
            held.append(name)
        else:
            called.add(name)
    if server.garbage:
        failures.append(f"the server wrote {len(server.garbage)} lines to stdout that are not JSON-RPC messages (first: {server.garbage[0]!r}); logs belong on stderr")
    not_called = sorted(set(by_name) - called)
    if not_called:
        print(f"NOT CALLED (their answers are not verified): {', '.join(not_called)}")
    for line in failures:
        print("FAIL " + line)
    print(f"summary: {len(tools)} tools listed, {len(called)} called and correct, {len(held)} held back, {len(failures)} failed checks; stderr in {log_path}")

    if failures:
        return end("fail", f"{len(failures)} checks failed; first: {failures[0]}")
    if held:
        return end("not verified", f"{len(held)} named calls were held back ({', '.join(held)}); see the HELD lines")
    if not calls:
        return end("not verified", f"the server started and its {len(tools)} tool schemas are well formed, but no tool was called. Name read-only tools and arguments with --call")
    return end("pass", f"{len(called)} of {len(by_name)} tools were called and answered as their schemas say" + (f"; {len(not_called)} were not called" if not_called else ""))


if __name__ == "__main__":
    sys.exit(main())

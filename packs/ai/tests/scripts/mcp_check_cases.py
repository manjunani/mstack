"""Script test for mcp-check: run probe.py against a tiny fake stdio MCP server in each of its modes.

The fake server (fixtures/fake_mcp_server.py) is copied into the run folder. It logs every tools/call it
receives, so each case can prove which tools were called and which were not.

Usage: mcp_check_cases.py <folder>   (a new run folder is made inside it, for example .testrun/ai-mcp-check)
"""
import argparse
import json
import pathlib
import sys

import casekit

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("folder")
args = parser.parse_args()
t = casekit.Cases("mcp-check cases", args.folder)
PROBE = casekit.SKILLS / "mcp-check" / "scripts" / "probe.py"
fixture = pathlib.Path(__file__).resolve().parent / "fixtures" / "fake_mcp_server.py"
server_file = t.write("fake_server.py", fixture.read_text(encoding="utf-8"))
counter = 0


def probe(label, mode, extra, want, contains=(), absent=(), calls_made=None):
    """Run one case with its own call log, then compare the log with calls_made (a list of tool names)."""
    global counter
    counter += 1
    log = t.root / f"calls-{counter:02d}.log"
    command = f'"{sys.executable}" "{server_file}" --mode {mode} --log "{log}"'
    t.run(label, PROBE, ["--server", command, *extra], want, contains=contains, absent=absent)
    if calls_made is not None:
        made = log.read_text(encoding="utf-8").split() if log.exists() else []
        t.check(f"  the server received exactly these calls: {calls_made}", made == calls_made, f"received {made}")


ADD = ["--call", "add", '{"a": 1, "b": 2}']
ECHO = ["--call", "echo", '{"text": "hi", "style": "upper"}']
probe("no call named: not verified, nothing called", "good", [], 2,
      contains=["3 tools in 1 page", "no tool was called", "not checked: schema keywords outside this script's subset: minLength"], calls_made=[])
probe("two read-only tools called and correct", "good", ADD + ECHO, 0,
      contains=["CALL add", "answered: 3", "answered: HI", "NOT CALLED (their answers are not verified): delete_everything"], calls_made=["add", "echo"])
probe("a tool not marked read-only is held back", "good", ADD + ["--call", "delete_everything", "{}"], 2,
      contains=["HELD", "--allow-write"], calls_made=["add"])
probe("the same tool is called with --allow-write", "good", ["--call", "delete_everything", "{}", "--allow-write"], 0,
      contains=["stub: nothing was deleted"], calls_made=["delete_everything"])
probe("arguments that do not fit the schema are not sent", "good", ["--call", "add", '{"a": "x", "b": 2}'], 2,
      contains=["HELD", "is not of type"], calls_made=[])
probe("an enum value outside the list is not sent", "good", ["--call", "echo", '{"text": "hi", "style": "loud"}'], 2,
      contains=["is not one of"], calls_made=[])
probe("a tool the server does not list fails", "good", ["--call", "subtract", "{}"], 1, contains=["lists no tool with this name"], calls_made=[])

t.json("calls.json", [{"tool": "add", "arguments": {"a": 1, "b": 2}, "expect_contains": "3"},
                      {"tool": "add", "arguments": {"a": "x"}, "expect_error": True}])
probe("a calls file with an expected answer and an expected refusal", "good", ["--calls-file", "calls.json"], 0,
      contains=["refused as expected"], calls_made=["add", "add"])
t.json("calls-wrong.json", [{"tool": "add", "arguments": {"a": 1, "b": 2}, "expect_contains": "999"}])
probe("an answer without the expected text fails", "good", ["--calls-file", "calls-wrong.json"], 1, contains=["does not contain '999'"])
t.json("calls-no-refusal.json", [{"tool": "echo", "arguments": {"text": "x"}, "expect_error": True}])
probe("an expected refusal that succeeds fails", "good", ["--calls-file", "calls-no-refusal.json"], 1, contains=["an error was expected"])

probe("malformed schemas fail, tool by tool", "bad-schema", [], 1,
      contains=['type "strng" is not a JSON Schema type', "required names 'region', which is not in properties",
                "enum has to be a list with at least one value", 'enum value "two" does not have the declared type', 'inputSchema.type is "array"'],
      calls_made=[])
probe("an answer that breaks the output schema fails", "wrong-output", ADD, 1, contains=["does not fit the tool's output schema", '"three" is not of type "number"'])
probe("two tools with one name fail", "duplicate", [], 1, contains=["used by more than one tool"])
probe("a server that exits at once is blocked", "crash", ADD, 2, contains=["RESULT blocked", "cannot open the config file"], calls_made=[])
probe("a server that never answers fails after the timeout", "silent", ["--timeout", "1"], 1, contains=["no answer to initialize within 1 seconds"])
probe("log lines on stdout fail", "chatty", ADD, 1, contains=["not JSON-RPC messages"])
probe("a paged tool list is followed", "paged", ADD, 0, contains=["3 tools in 2 pages"], calls_made=["add"])
probe("an older protocol revision is reported, not failed", "old", ADD, 0, contains=["the server speaks 2024-11-05"])
probe("a missing tools capability fails", "no-tools-cap", ADD, 1, contains=["does not declare the tools capability"])

t.run("a command that does not exist is blocked", PROBE, ["--server", "no-such-command-mstack-test --x"], 2, contains=["RESULT blocked", "could not be started"])
t.run("arguments that are not JSON are blocked", PROBE, ["--server", "true", "--call", "add", "{a:1}"], 2, contains=["RESULT blocked", "not JSON"])
t.check("stderr of the last server run was saved", (t.root / ".mstack" / "mcp-check" / "server-stderr.log").exists())
t.check(".mstack/.gitignore lists the log folder", "mcp-check/" in (t.root / ".mstack" / ".gitignore").read_text())
sys.exit(t.done())

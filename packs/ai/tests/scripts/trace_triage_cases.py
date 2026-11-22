"""Script test for trace-triage: traces with a known fault at a known line, in each shape the script reads.

Usage: trace_triage_cases.py <folder>   (a new run folder is made inside it, for example .testrun/ai-trace-triage)
"""
import argparse
import json
import sys

import casekit

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("folder")
args = parser.parse_args()
t = casekit.Cases("trace-triage cases", args.folder)
TRIAGE = casekit.SKILLS / "trace-triage" / "scripts" / "triage.py"


def user(text):
    return {"role": "user", "content": text}


def say(text, calls=(), usage=None):
    row = {"role": "assistant", "content": text}
    if calls:
        row["tool_calls"] = [{"id": i, "name": n, "arguments": a} for i, n, a in calls]
    if usage:
        row["usage"] = usage
    return row


def tool(ident, text, error=False):
    row = {"role": "tool", "tool_call_id": ident, "content": text}
    if error:
        row["is_error"] = True
    return row


clean = [user("What is our refund window?"),
         say("I will look it up.", [("c1", "search", {"q": "refund window"})]), tool("c1", "doc 7: refunds within 30 days"),
         say("", [("c2", "read", {"id": 7})]), tool("c2", "Refunds are accepted within 30 days of delivery."),
         say("The refund window is 30 days from delivery.")]
t.jsonl("clean.jsonl", clean)
t.run("a clean run passes", TRIAGE, ["clean.jsonl"], 0, contains=["first failing step: none", "last turn that made progress: line 6"],
      absent=["REPEAT", "IGNORED", "NO PROGRESS"])

loop = [user("Find the refund policy.")]
for i in range(1, 5):
    loop += [say("Searching.", [(f"c{i}", "search", {"q": "refund policy"})]), tool(f"c{i}", "no results")]
loop.append(say("I could not find it."))
t.jsonl("loop.jsonl", loop)
t.run("four identical calls are reported with their lines", TRIAGE, ["loop.jsonl"], 1,
      contains=["REPEAT search", "4 identical calls at lines 2, 4, 6, 8 (4 in a row)", "NO PROGRESS line 4", "NO PROGRESS line 8", "last turn that made progress: line 10"])

ignored = [user("Fix the date parser and run the tests."),
           say("Running the tests.", [("c1", "run_tests", {"path": "tests/"})]), tool("c1", "Error: exit code 1, 3 tests failed", error=True),
           say("Running the tests.", [("c2", "run_tests", {"path": "tests/"})]), tool("c2", "Error: exit code 1, 3 tests failed", error=True),
           say("All done. The parser now handles every format.")]
t.jsonl("ignored.jsonl", ignored)
t.run("an unchanged retry and a silent finish are both reported", TRIAGE, ["ignored.jsonl"], 1,
      contains=["first failing step: line 3, tool run_tests (flagged)", "IGNORED line 3 run_tests error", "line 4 made the same call again, unchanged",
                "IGNORED line 5 run_tests error", "line 6 answered without a word about the error"])

handled = [user("Download the price list."),
           say("Fetching.", [("c1", "fetch", {"url": "https://a.example/prices"})]), tool("c1", "Error: 503", error=True),
           say("The first address failed, so I will use the mirror instead.", [("c2", "fetch", {"url": "https://b.example/prices"})]), tool("c2", "widget 4.00"),
           say("The price list has one item: widget, 4.00.")]
t.jsonl("handled.jsonl", handled)
t.run("an error answered with a changed call passes", TRIAGE, ["handled.jsonl"], 0,
      contains=["first failing step: line 3", "tool errors: 1 (1 followed by a changed call or a mention of the failure)"], absent=["IGNORED"])

big = "x" * 5000
blocks = [{"role": "user", "content": "Summarise config.yaml"},
          {"role": "assistant", "content": [{"type": "text", "text": "Reading it."}, {"type": "tool_use", "id": "t1", "name": "read_file", "input": {"path": "config.yaml"}}],
           "usage": {"input_tokens": 900, "output_tokens": 40}},
          {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": big}]}]},
          {"role": "assistant", "content": [{"type": "tool_use", "id": "t2", "name": "read_file", "input": {"path": "secrets.yaml"}}],
           "usage": {"input_tokens": 400, "cache_read_input_tokens": 2100, "output_tokens": 25}}]
t.jsonl("blocks.jsonl", blocks)
t.run("message blocks: size, tokens and a cut-off ending", TRIAGE, ["blocks.jsonl"], 1,
      contains=["shape: blocks", "line 3: result of read_file: 5,000 characters", "context 900 at line 2, 2,500 at line 4, peak 2,500 at line 4; output 65",
                "UNFINISHED line 4: the trace ends on a call to read_file with no result"])

session = [{"type": "summary", "summary": "earlier work"},
           {"type": "user", "message": {"role": "user", "content": "Deploy the docs."}},
           {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "s1", "name": "Bash", "input": {"command": "make docs"}}]}},
           {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "s1", "content": "Traceback (most recent call last):\n  File \"build.py\"\nKeyError: 'title'"}]}},
           {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "The docs are deployed."}]}}]
t.jsonl("session.jsonl", session)
t.run("session rows: an error seen only in its text, then ignored", TRIAGE, ["session.jsonl"], 1,
      contains=["shape: session", "1 other rows skipped", "first failing step: line 4, tool Bash (by its text)", "line 5 answered without a word about the error"])

t.write("part.jsonl", "".join(json.dumps(r) + "\n" for r in clean[:3]) + "{this line was cut off\n" + "".join(json.dumps(r) + "\n" for r in clean[3:]))
t.run("an unreadable line makes a clean result not verified", TRIAGE, ["part.jsonl"], 2, contains=["RESULT not verified", "first at line 4"])

crash = clean[:3] + [{"type": "error", "message": "rate limit reached, run stopped"}]
t.jsonl("crash.jsonl", crash)
t.run("a run error row is reported", TRIAGE, ["crash.jsonl"], 1, contains=["RUN ERROR line 4", "first failing step: line 4, run error"])

poll = [user("Wait for the build."),
        say("Checking.", [("p1", "build_status", {"id": 5})]), tool("p1", "running"),
        say("Checking again.", [("p2", "build_status", {"id": 5})]), tool("p2", "finished"),
        say("The build finished.")]
t.jsonl("poll.jsonl", poll)
t.run("polling twice with a new result passes", TRIAGE, ["poll.jsonl"], 0)
t.run("the same trace fails with --repeat-min 2", TRIAGE, ["poll.jsonl", "--repeat-min", "2"], 1, contains=["2 identical calls at lines 2, 4"])

fn = [user("Count the rows.")]
for i, raw in enumerate(['{"table": "orders", "limit": 5}', '{"limit":5,"table":"orders"}', '{ "table":"orders",  "limit": 5 }'], 1):
    fn.append({"role": "assistant", "content": None, "tool_calls": [{"id": f"call_{i}", "type": "function", "function": {"name": "sql", "arguments": raw}}]})
    fn.append({"role": "tool", "tool_call_id": f"call_{i}", "content": f"result page {i}"})
fn.append(say("There are 5 rows."))
t.jsonl("function-style.jsonl", fn)
t.run("argument strings that differ only in order and spacing count as identical", TRIAGE, ["function-style.jsonl"], 1, contains=["3 identical calls at lines 2, 4, 6"])

t.run("findings can be written to a new JSON file", TRIAGE, ["loop.jsonl", "--json", "findings.json"], 1, contains=["findings written to findings.json"])
t.check("the JSON file holds the findings", json.loads((t.root / "findings.json").read_text())["findings"][0]["kind"] == "REPEAT")
t.run("an existing JSON file is not overwritten", TRIAGE, ["loop.jsonl", "--json", "findings.json"], 2, contains=["RESULT blocked", "already exists"])
t.jsonl("not-a-trace.jsonl", [{"case": "a", "pass": True}, {"case": "b", "pass": False}])
t.run("a file with no trace rows is blocked", TRIAGE, ["not-a-trace.jsonl"], 2, contains=["RESULT blocked", "no assistant turns"])
t.run("a missing file is blocked", TRIAGE, ["nope.jsonl"], 2, contains=["RESULT blocked: no trace file"])
sys.exit(t.done())

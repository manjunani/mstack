#!/usr/bin/env python3
"""Read the saved trace of an agent run and name where it went wrong.

  triage.py <trace.jsonl> [--repeat-min 3] [--top 5] [--json <new file>]

The trace is JSON lines, one message or event per line. Three shapes are read:
  rows      {"role": "assistant", "content": "...", "tool_calls": [{"id": "c1", "name": "search", "arguments": {...}}], "usage": {...}}
            {"role": "tool", "tool_call_id": "c1", "content": "...", "is_error": true}
  blocks    {"role": "assistant", "content": [{"type": "text", ...}, {"type": "tool_use", "id": ..., "name": ..., "input": {...}}]}
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": ..., "content": ..., "is_error": true}]}
  session   {"type": "assistant", "message": {...one of the shapes above...}}
An event such as {"type": "error", "message": "..."} counts as a run error.

It reports, with line numbers:
  REPEAT        one identical tool call made --repeat-min times or more
  IGNORED       a tool error after which the agent repeated the same call unchanged, or carried on without a word about it
  NO PROGRESS   a turn that only repeated earlier calls and got the same results, or said nothing new
  UNFINISHED    the trace ends on a tool call or tool result, with no final answer
  the first failing step, the last turn that made progress, and the largest context contributors
It reads the file only. It does not judge whether the final answer is right.

Exit codes: 0 = pass: none of the patterns above was found
            1 = fail: at least one was found
            2 = not verified (part of the file could not be read) or blocked (no file, or no trace rows in it)
The last line printed is the result.
"""
import argparse
import json
import pathlib
import re
import sys

DEFAULTS = pathlib.Path(__file__).resolve().parent.parent / "references" / "defaults.json"
ERROR_TEXT = re.compile(r"^\W*(error\b|traceback \(most recent call last\)|exception\b|fatal\b|command failed|exit code [1-9]|permission denied)", re.I)
ADMITS = re.compile(r"\b(error|errors|fail|fails|failed|failure|unable|could not|couldn't|cannot|can't|did not work|didn't work|"
                    r"retry|retrying|instead|problem|issue|sorry|exception|denied|timeout|timed out|not found|invalid|wrong|fix|broken|missing)\b", re.I)


def end(state, why=""):
    why = " ".join(str(why).split())  # the result stays on one line, whatever text it quotes
    print(f"RESULT {state}" + (f": {why}" if why else ""))
    return {"pass": 0, "fail": 1}.get(state, 2)


def text_of(content):
    """Flatten message content (a string, or a list of blocks) into plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(text_of(c.get("text", c.get("content", "")) if isinstance(c, dict) else c) for c in content)
    if isinstance(content, dict):
        return text_of(content.get("text", content.get("content", json.dumps(content, sort_keys=True))))
    return str(content)


def canon(arguments):
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            return arguments.strip()
    return json.dumps(arguments, sort_keys=True, separators=(",", ":"))


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def read_usage(usage):
    """Return (context tokens, output tokens) or (None, None)."""
    if not isinstance(usage, dict):
        return None, None
    sent = number(usage.get("input_tokens"))
    if sent is None:
        sent = number(usage.get("prompt_tokens"))
    extra = sum(number(usage.get(k)) or 0 for k in ("cache_read_input_tokens", "cache_creation_input_tokens"))
    out = number(usage.get("output_tokens"))
    if out is None:
        out = number(usage.get("completion_tokens"))
    return (sent + extra if sent is not None else None), out


def is_error(row_or_block, text):
    if row_or_block.get("is_error") is True or row_or_block.get("isError") is True:
        return "flagged"
    if row_or_block.get("error") or str(row_or_block.get("status", "")).lower() in ("error", "failed", "failure"):
        return "flagged"
    if ERROR_TEXT.search(text[:200]):
        return "by its text"
    return ""


def parse_line(row):
    """Turn one trace row into an event dict, or None if the row is not part of the conversation."""
    shape = "rows"
    if isinstance(row.get("message"), dict) and ("role" in row["message"] or "content" in row["message"]):
        outer, row, shape = row, dict(row["message"]), "session"
        row.setdefault("role", outer.get("type"))
        if "usage" not in row and isinstance(outer.get("usage"), dict):
            row["usage"] = outer["usage"]
    role = str(row.get("role") or "").lower()
    if not role and str(row.get("type", "")).lower() == "error" or role == "error":
        detail = row.get("error", row.get("message", row.get("content", "")))
        return {"kind": "error", "text": text_of(detail) if not isinstance(detail, dict) else json.dumps(detail, sort_keys=True),
                "calls": [], "results": [], "shape": shape}
    if role not in ("assistant", "user", "system", "tool", "function", "developer", "model"):
        return None
    event = {"kind": "assistant" if role in ("assistant", "model") else "tool" if role in ("tool", "function") else "user",
             "text": "", "calls": [], "results": [], "shape": shape}
    event["context"], event["output"] = read_usage(row.get("usage"))
    content = row.get("content")
    texts = []
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                texts.append(str(block))
                continue
            kind = block.get("type")
            if kind == "tool_use":
                event["calls"].append({"id": block.get("id"), "name": str(block.get("name", "?")), "args": canon(block.get("input", {}))})
                event["shape"] = "blocks" if shape == "rows" else shape
            elif kind == "tool_result":
                body = text_of(block.get("content"))
                event["results"].append({"id": block.get("tool_use_id"), "name": None, "text": body, "error": is_error(block, body)})
                event["shape"] = "blocks" if shape == "rows" else shape
            else:
                texts.append(text_of(block))
    else:
        texts.append(text_of(content))
    for call in row.get("tool_calls") or []:
        if not isinstance(call, dict):
            continue
        inner = call.get("function") if isinstance(call.get("function"), dict) else call
        event["calls"].append({"id": call.get("id"), "name": str(inner.get("name", "?")), "args": canon(inner.get("arguments", inner.get("input", {})))})
    if event["kind"] == "tool":
        body = "\n".join(t for t in texts if t)
        event["results"].append({"id": row.get("tool_call_id", row.get("tool_use_id")), "name": row.get("name"), "text": body, "error": is_error(row, body)})
        texts = []
    if event["results"] and event["kind"] == "user":
        event["kind"] = "tool"
    event["text"] = "\n".join(t for t in texts if t).strip()
    return event


def load(path):
    events, unread, other = [], [], 0
    for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            unread.append(line_no)
            continue
        event = parse_line(row) if isinstance(row, dict) else None
        if event is None:
            other += 1
            continue
        event["line"] = line_no
        events.append(event)
    return events, unread, other


def link_results(events):
    """Give every call its result (text, error) and every result its tool name."""
    waiting, by_id = [], {}
    for event in events:
        for call in event["calls"]:
            call["line"] = event["line"]
            call["result"] = None
            waiting.append(call)
            if call["id"] is not None:
                by_id[call["id"]] = call
        for result in event["results"]:
            result["line"] = event["line"]
            call = by_id.get(result["id"]) if result["id"] is not None else None
            if call is None and result["id"] is None and waiting:
                call = next((c for c in waiting if c["result"] is None), None)
            if call is not None and call["result"] is None:
                call["result"] = result
                result["name"] = result["name"] or call["name"]
                result["call"] = call
            result["name"] = result["name"] or "?"


def short(text, limit=110):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 3] + "..."


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    try:
        raw = json.loads(DEFAULTS.read_text(encoding="utf-8"))
        repeat_default, top_default = raw["repeat_min"]["value"], raw["top"]["value"]
    except (OSError, ValueError, KeyError) as exc:
        return end("blocked", f"the defaults file {DEFAULTS} cannot be used ({exc})")
    parser.add_argument("trace", help="the trace file, JSON lines")
    parser.add_argument("--repeat-min", type=int, default=repeat_default, help="report an identical call made this many times (default %(default)s)")
    parser.add_argument("--top", type=int, default=top_default, help="how many context contributors to list (default %(default)s)")
    parser.add_argument("--json", help="also write the findings as JSON to this new file (an existing file is not overwritten)")
    args = parser.parse_args()
    path = pathlib.Path(args.trace)
    if not path.is_file():
        return end("blocked", f"no trace file at {path}")
    if args.repeat_min < 2:
        return end("blocked", "--repeat-min needs 2 or more")
    if args.json and pathlib.Path(args.json).exists():
        return end("blocked", f"{args.json} already exists; name a new file")
    events, unread, other = load(path)
    turns = [e for e in events if e["kind"] == "assistant"]
    if not events or not turns:
        return end("blocked", f"{path} holds no assistant turns this script can read ({len(events)} rows recognised, {len(unread)} lines not JSON, {other} other rows). See --help for the shapes it reads")
    link_results(events)

    calls = [c for e in events for c in e["calls"]]
    results = [r for e in events for r in e["results"]]
    errors = [r for r in results if r["error"]]
    run_errors = [e for e in events if e["kind"] == "error"]
    shapes = sorted({e["shape"] for e in events})
    print(f"trace: {path}: {len(events)} rows read, {len(turns)} assistant turns, {len(calls)} tool calls, {len(results)} tool results "
          f"({len(errors)} errors), {len(run_errors)} run errors, {len(unread)} lines not read, {other} other rows skipped")
    print(f"shape: {', '.join(shapes)}   settings: an identical call is reported from {args.repeat_min} times (an mstack default, not a measured value)")
    findings = []

    # Repeated identical calls
    groups = {}
    for call in calls:
        groups.setdefault((call["name"], call["args"]), []).append(call["line"])
    order = [(c["name"], c["args"]) for c in calls]
    for key, lines in groups.items():
        if len(lines) < args.repeat_min:
            continue
        run = best = 0
        for item in order:
            run = run + 1 if item == key else 0
            best = max(best, run)
        findings.append({"kind": "REPEAT", "line": lines[0], "tool": key[0],
                         "text": f"{key[0]} {short(key[1], 70)}: {len(lines)} identical calls at lines {', '.join(map(str, lines))}" + (f" ({best} in a row)" if best > 1 else "")})

    # Tool errors that were ignored
    handled = 0
    for result in errors:
        position = next(i for i, e in enumerate(events) if e["line"] == result["line"])
        follow = next((e for e in events[position + 1:] if e["kind"] == "assistant"), None)
        call = result.get("call")
        label = f"line {result['line']} {result['name']} error ({result['error']}): {short(result['text'], 70)!r}"
        if follow is None:
            continue  # reported below as an unfinished run
        same_tool = [c for c in follow["calls"] if call and c["name"] == call["name"]]
        if call and any(c["args"] == call["args"] for c in same_tool):
            findings.append({"kind": "IGNORED", "line": result["line"], "tool": result["name"],
                             "text": f"{label} -> line {follow['line']} made the same call again, unchanged"})
        elif same_tool or ADMITS.search(follow["text"]):
            handled += 1
        else:
            what = "went on to " + ", ".join(sorted({c["name"] for c in follow["calls"]})) if follow["calls"] else "answered"
            findings.append({"kind": "IGNORED", "line": result["line"], "tool": result["name"],
                             "text": f"{label} -> line {follow['line']} {what} without a word about the error"})

    # Turns with no progress
    seen_calls, seen_text, stalled = {}, set(), []
    for event in turns:
        key_text = " ".join(event["text"].split()).lower()
        if event["calls"]:
            stale = all((c["name"], c["args"]) in seen_calls and c["result"] is not None
                        and c["result"]["text"] in seen_calls[(c["name"], c["args"])] for c in event["calls"])
            if stale:
                stalled.append((event["line"], "every call repeats an earlier one and got the same result"))
        elif not key_text:
            stalled.append((event["line"], "no text and no tool call"))
        elif len(key_text) >= 20 and key_text in seen_text:
            stalled.append((event["line"], "the same text as an earlier turn"))
        for c in event["calls"]:
            seen_calls.setdefault((c["name"], c["args"]), set())
            if c["result"] is not None:
                seen_calls[(c["name"], c["args"])].add(c["result"]["text"])
        if key_text:
            seen_text.add(key_text)
    for line, why in stalled:
        findings.append({"kind": "NO PROGRESS", "line": line, "tool": None, "text": f"line {line}: {why}"})
    for event in run_errors:
        findings.append({"kind": "RUN ERROR", "line": event["line"], "tool": None, "text": f"line {event['line']}: {short(event['text'], 120)}"})

    # A run that stops before a final answer
    last = events[-1]
    if last["kind"] == "assistant" and last["calls"] and any(c["result"] is None for c in last["calls"]):
        findings.append({"kind": "UNFINISHED", "line": last["line"], "tool": last["calls"][-1]["name"],
                         "text": f"line {last['line']}: the trace ends on a call to {last['calls'][-1]['name']} with no result (cut off, stopped, or out of turns)"})
    elif last["kind"] == "tool":
        tail = " that is an error" if any(r["error"] for r in last["results"]) else ""
        findings.append({"kind": "UNFINISHED", "line": last["line"], "tool": None,
                         "text": f"line {last['line']}: the trace ends on a tool result{tail}, with no answer after it"})

    first_fail = min([r["line"] for r in errors] + [e["line"] for e in run_errors], default=None)
    print()
    if first_fail is None:
        print("first failing step: none (no tool error and no run error in the file)")
    else:
        hit = next((r for r in errors if r["line"] == first_fail), None)
        if hit:
            print(f"first failing step: line {first_fail}, tool {hit['name']} ({hit['error']}): {short(hit['text'], 140)!r}")
        else:
            print(f"first failing step: line {first_fail}, run error: {short(next(e for e in run_errors if e['line'] == first_fail)['text'], 140)!r}")
    stalled_lines = {line for line, _ in stalled}
    moving = [e["line"] for e in turns if e["line"] not in stalled_lines and (e["calls"] or e["text"])]
    print(f"last turn that made progress: line {moving[-1]}" if moving else "last turn that made progress: none")
    print(f"tool errors: {len(errors)} ({handled} followed by a changed call or a mention of the failure)")
    findings.sort(key=lambda f: f["line"])
    for finding in findings:
        print(f"{finding['kind']} {finding['text']}")

    # Largest context contributors
    sized = []
    for event in events:
        if event["text"]:
            sized.append((len(event["text"]), event["line"], f"{event['kind']} text"))
        for c in event["calls"]:
            sized.append((len(c["args"]), event["line"], f"arguments of {c['name']}"))
        for r in event["results"]:
            sized.append((len(r["text"]), event["line"], f"result of {r['name']}"))
    total = sum(s for s, _, _ in sized) or 1
    print(f"\nlargest context contributors (characters of content; {total:,} in the whole trace)")
    for size, line, what in sorted(sized, reverse=True)[:max(1, args.top)]:
        print(f"  line {line}: {what}: {size:,} characters ({size / total:.0%})")
    per_tool = {}
    for r in results:
        per_tool[r["name"]] = per_tool.get(r["name"], 0) + len(r["text"])
    if per_tool:
        print("  by tool (results): " + ", ".join(f"{name} {size:,}" for name, size in sorted(per_tool.items(), key=lambda kv: -kv[1])[:max(1, args.top)]))
    counted = [(e["line"], e["context"]) for e in turns if e.get("context") is not None]
    if counted:
        peak = max(counted, key=lambda lc: lc[1])
        produced = sum(e["output"] or 0 for e in turns)
        print(f"tokens (from the trace's own usage fields): context {counted[0][1]:,} at line {counted[0][0]}, {counted[-1][1]:,} at line {counted[-1][0]}, "
              f"peak {peak[1]:,} at line {peak[0]}; output {produced:,} over {len(counted)} turns")
    else:
        print("tokens: the trace holds no usage fields, so sizes above are characters, not tokens")
    print("not judged here: whether the final answer is right, and anything that happened outside this file")

    if args.json:
        summary = {"trace": str(path), "rows": len(events), "assistant_turns": len(turns), "tool_calls": len(calls), "tool_errors": len(errors),
                   "lines_not_read": unread, "first_failing_line": first_fail, "last_progress_line": moving[-1] if moving else None,
                   "findings": findings}
        pathlib.Path(args.json).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(f"findings written to {args.json}")

    if findings:
        counts = {}
        for f in findings:
            counts[f["kind"]] = counts.get(f["kind"], 0) + 1
        where = f"first failing step at line {first_fail}; " if first_fail is not None else ""
        gap = f"; {len(unread)} lines could not be read" if unread else ""
        return end("fail", where + ", ".join(f"{n} {k.lower()}" for k, n in counts.items()) + f"; earliest finding at line {findings[0]['line']}" + gap)
    if unread:
        return end("not verified", f"nothing was found in the rows that were read, but {len(unread)} lines are not JSON (first at line {unread[0]}), so part of the run was not checked")
    return end("pass", f"none of the patterns was found in {len(turns)} assistant turns and {len(calls)} tool calls; the answer itself was not judged")


if __name__ == "__main__":
    sys.exit(main())

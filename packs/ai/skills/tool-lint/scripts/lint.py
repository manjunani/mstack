#!/usr/bin/env python3
"""Check tool definitions before a model sees them.

  lint.py <tools.json> [<more.json> ...] [--strict] [--json <new file>]

A file holds a JSON list of tools, an object with a "tools" list, or one tool. Each tool is read in any of
these shapes: {name, description, input_schema}, {name, description, inputSchema}, {name, description,
parameters}, or {"type": "function", "function": {name, description, parameters}}.

FAIL lines are facts that break or confuse tool use:
  no name; two tools with one name, or names that differ only in case and separators; no description;
  no input schema, or one whose type is not "object"; a required list that is malformed or names a
  parameter that does not exist; a parameter with no type; an empty enum; two tools whose descriptions
  are nearly the same text.
WARN lines are judgement calls to read:
  an unclear name (generic, very short, numbered); names that are near copies of each other; a name
  outside the usual provider limits; a description that is short, repeats the name, or does not say
  when to use the tool; parameters with no required list; a parameter with no description; an array
  with no items; two tools whose descriptions overlap heavily.

Exit codes: 0 = pass: no FAIL line (WARN lines may be present; --strict turns them into a fail)
            1 = fail
            2 = blocked: a file is missing, is not JSON, or holds no tool definitions
The last line printed is the result.
"""
import argparse
import itertools
import json
import pathlib
import re
import sys

LIMITS = pathlib.Path(__file__).resolve().parent.parent / "references" / "limits.json"
GENERIC = {"run", "do", "tool", "tools", "helper", "process", "handle", "handler", "execute", "exec", "data", "misc", "util", "utils",
           "function", "func", "action", "call", "query", "api", "request", "command", "cmd", "task", "main", "test", "thing", "stuff",
           "get", "set", "update", "manage", "info", "item", "object", "resource", "operation", "op", "method", "service", "work"}
STOP = set("a an the and or of to in on for with is are be it this that these those by as at from into its their your you can will "
           "which what who how not no any all each one given using use used uses via per if when then than also only".split())
WHEN = re.compile(r"\b(use (this|it|when|if|for|to|only|after|before|whenever)|used (to|for|when)|when|whenever|if (the|a|an|you|your|there|no)|"
                  r"before|after|instead of|rather than|not for|do not use|don't use|only for|call this|prefer this|"
                  r"for (questions|requests|tasks|cases|anything|any))\b", re.I)
OPEN_TYPE = ("enum", "const", "anyOf", "oneOf", "allOf", "$ref", "not")


def end(state, why=""):
    why = " ".join(str(why).split())  # the result stays on one line, whatever text it quotes
    print(f"RESULT {state}" + (f": {why}" if why else ""))
    return {"pass": 0, "fail": 1}.get(state, 2)


def words(text):
    out = set()
    for w in re.findall(r"[a-z0-9]+", str(text).lower()):
        if w in STOP or len(w) < 3:
            continue
        for tail in ("ing", "ed", "es", "s"):
            if len(w) > len(tail) + 3 and w.endswith(tail):
                w = w[:-len(tail)]
                break
        out.add(w)
    return out


def name_parts(name):
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    return [p for p in re.split(r"[^A-Za-z0-9]+", spaced.lower()) if p]


def close(a, b):
    """True when two strings differ by at most one inserted, removed or changed character."""
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1:] or a[i + 1:] == b[i + 1:]


def read_tools(path):
    """Return a list of {name, description, schema, where} from one file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("tools"), list):
        data = data["tools"]
    elif isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return []
    tools = []
    for index, raw in enumerate(data, 1):
        if not isinstance(raw, dict):
            continue
        inner = raw["function"] if isinstance(raw.get("function"), dict) else raw
        schema = next((inner[k] for k in ("input_schema", "inputSchema", "parameters") if k in inner), None)
        if "name" not in inner and "description" not in inner and schema is None:
            continue
        tools.append({"name": inner.get("name"), "description": inner.get("description"), "schema": schema,
                      "where": f"{path.name}#{index}", "size": len(json.dumps(raw))})
    return tools


def lint_schema(schema, where, add):
    """Walk the parameters of an object schema."""
    props = schema.get("properties")
    if "properties" in schema and not isinstance(props, dict):
        add("FAIL", f"{where}: properties is not an object")
        props = None
    required = schema.get("required")
    if "required" in schema:
        if not isinstance(required, list) or any(not isinstance(r, str) for r in required):
            add("FAIL", f"{where}: required is not a list of parameter names")
        else:
            for name in required:
                if not props or name not in props:
                    add("FAIL", f"{where}: required names '{name}', which is not a parameter")
            if len(set(required)) != len(required):
                add("FAIL", f"{where}: required names a parameter twice")
    elif props:
        add("WARN", f"{where}: {len(props)} parameters and no required list, so every one is optional; write the list, or \"required\": [] to say so on purpose")
    for key, sub in (props or {}).items():
        spot = f"{where}.{key}"
        if not isinstance(sub, dict):
            add("FAIL", f"{spot}: the parameter's schema is not an object")
            continue
        if "type" not in sub and not any(k in sub for k in OPEN_TYPE):
            add("FAIL", f"{spot}: no type")
        if "enum" in sub and (not isinstance(sub["enum"], list) or not sub["enum"]):
            add("FAIL", f"{spot}: enum is empty or not a list")
        if not isinstance(sub.get("description"), str) or not sub["description"].strip():
            add("WARN", f"{spot}: no description")
        kind = sub.get("type")
        if kind == "array" or (isinstance(kind, list) and "array" in kind):
            if not isinstance(sub.get("items"), dict):
                add("WARN", f"{spot}: an array with no items schema")
            elif sub["items"].get("type") == "object" or "properties" in sub["items"]:
                lint_schema(sub["items"], spot + "[]", add)
            elif "type" not in sub["items"] and not any(k in sub["items"] for k in OPEN_TYPE):
                add("FAIL", f"{spot}[]: the items have no type")
        if kind == "object" or "properties" in sub:
            lint_schema(sub, spot, add)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    try:
        limits = json.loads(LIMITS.read_text(encoding="utf-8"))
        min_words, warn_at, fail_at = (limits[k]["value"] for k in ("min_description_words", "overlap_warn", "overlap_fail"))
        max_len, pattern = limits["name_max_length"]["value"], re.compile(limits["name_pattern"]["value"])
    except (OSError, ValueError, KeyError, re.error) as exc:
        return end("blocked", f"the limits file {LIMITS} cannot be used ({exc})")
    parser.add_argument("files", nargs="+", help="JSON files with tool definitions")
    parser.add_argument("--strict", action="store_true", help="count WARN lines as failures")
    parser.add_argument("--overlap-warn", type=float, default=warn_at, help="report a pair of descriptions from this share of common words (default %(default)s)")
    parser.add_argument("--overlap-fail", type=float, default=fail_at, help="fail a pair of descriptions from this share of common words (default %(default)s)")
    parser.add_argument("--min-words", type=int, default=min_words, help="report a description with fewer words (default %(default)s)")
    parser.add_argument("--json", help="also write the findings as JSON to this new file (an existing file is not overwritten)")
    args = parser.parse_args()
    if args.json and pathlib.Path(args.json).exists():
        return end("blocked", f"{args.json} already exists; name a new file")
    if not 0 < args.overlap_warn <= args.overlap_fail <= 1:
        return end("blocked", "--overlap-warn and --overlap-fail need values from 0 to 1, with warn at or below fail")

    tools = []
    for name in args.files:
        path = pathlib.Path(name)
        if not path.is_file():
            return end("blocked", f"no file at {path}")
        try:
            found = read_tools(path)
        except ValueError as exc:
            return end("blocked", f"{path} is not valid JSON ({exc})")
        if not found:
            return end("blocked", f"{path} holds no tool definitions (a list of objects with name, description and an input schema was expected)")
        tools += found

    findings = []

    def adder(label):
        return lambda level, text: findings.append({"level": level, "tool": label, "text": text})

    for tool in tools:
        name, desc, schema = tool["name"], tool["description"], tool["schema"]
        label = name if isinstance(name, str) and name.strip() else f"(no name, {tool['where']})"
        tool["label"] = label
        add = adder(label)
        if label != name:
            add("FAIL", "no name")
        else:
            parts = name_parts(name)
            if not pattern.match(name) or len(name) > max_len:
                add("WARN", f"name is outside the usual provider limits ({max_len} characters, pattern {pattern.pattern}); these limits are unverified, check your provider")
            base = re.sub(r"[_-]?\d+$", "", name)  # "tool2" and "helper_3" are numbered generic names; "oauth2_login" is not
            numbered = base != name and (not base or base.lower() in GENERIC)
            if len(name) < 3 or (len(parts) == 1 and parts[0] in GENERIC) or numbered:
                add("WARN", f"name '{name}' does not say what the tool does")
        if not isinstance(desc, str) or not desc.strip():
            add("FAIL", "no description")
        else:
            count = len(desc.split())
            if count < args.min_words:
                add("WARN", f"description has {count} words; a model needs more than that to choose this tool")
            if isinstance(name, str) and words(desc) <= words(" ".join(name_parts(name))):
                add("WARN", "description only repeats the name")
            if not WHEN.search(desc):
                add("WARN", "description does not say when to use the tool (no 'use when', 'use this to', 'when', 'instead of' or similar)")
        if not isinstance(schema, dict):
            add("FAIL", "no input schema")
        elif schema.get("type") != "object":
            add("FAIL", f"input schema type is {json.dumps(schema.get('type'))}, not \"object\"")
        else:
            lint_schema(schema, "parameters", add)

    named = [t for t in tools if t["label"] == t["name"]]
    for a, b in itertools.combinations(named, 2):
        pair = f"{a['name']} + {b['name']}"
        add = adder(pair)
        flat_a, flat_b = "".join(name_parts(a["name"])), "".join(name_parts(b["name"]))
        if a["name"] == b["name"]:
            add("FAIL", f"two tools are both named '{a['name']}' ({a['where']} and {b['where']})")
        elif flat_a == flat_b:
            add("FAIL", "the names differ only in case or separators")
        elif sorted(name_parts(a["name"])) == sorted(name_parts(b["name"])) or close(flat_a, flat_b):
            add("WARN", "the names are near copies of each other")
        wa, wb = words(a["description"] or ""), words(b["description"] or "")
        if a["name"] != b["name"] and len(wa) >= 4 and len(wb) >= 4:
            share = len(wa & wb) / len(wa | wb)
            if share >= args.overlap_fail:
                add("FAIL", f"the descriptions are nearly the same text ({share:.0%} of their words in common); a model cannot choose between them")
            elif share >= args.overlap_warn:
                add("WARN", f"the descriptions overlap heavily ({share:.0%} of their words in common); say what each is for and when to pick the other")

    findings = [f for i, f in enumerate(findings) if f not in findings[:i]]  # one line per distinct finding
    fails = [f for f in findings if f["level"] == "FAIL"]
    warns = [f for f in findings if f["level"] == "WARN"]
    total = sum(t["size"] for t in tools)
    biggest = max(tools, key=lambda t: t["size"])
    print(f"tools: {len(tools)} in {len(args.files)} file{'s' if len(args.files) != 1 else ''}; definitions are {total:,} characters in all (largest: {biggest['label']}, {biggest['size']:,})")
    print("note: thresholds and name limits come from references/limits.json and are unverified first settings; the flags change the thresholds.")
    for finding in fails + warns:
        print(f"{finding['level']} {finding['tool']}: {finding['text']}")
    clean = len({t["label"] for t in tools} - {f["tool"] for f in findings} - {n for f in findings for n in f["tool"].split(" + ")})
    print(f"summary: {len(fails)} FAIL, {len(warns)} WARN, {clean} of {len(tools)} tools with no finding")
    print("not checked: whether a model picks the right tool in practice, and schema keywords beyond type, properties, required, enum and items")
    if args.json:
        pathlib.Path(args.json).write_text(json.dumps({"tools": len(tools), "characters": total, "findings": findings}, indent=2) + "\n", encoding="utf-8")
        print(f"findings written to {args.json}")
    if fails:
        return end("fail", f"{len(fails)} FAIL lines; first: {fails[0]['tool']}: {fails[0]['text']}")
    if warns and args.strict:
        return end("fail", f"{len(warns)} WARN lines under --strict; first: {warns[0]['tool']}: {warns[0]['text']}")
    if warns:
        return end("pass", f"no FAIL line in {len(tools)} tools; {len(warns)} WARN lines are judgement calls to read")
    return end("pass", f"no finding in {len(tools)} tools")


if __name__ == "__main__":
    sys.exit(main())

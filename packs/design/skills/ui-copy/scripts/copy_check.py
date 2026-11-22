#!/usr/bin/env python3
"""Check the words of an interface: every visible string, with its role and where it is.

  check  read the strings and report what blocks and what only warns

The strings come from one of three places:
  --snapshot FILE   a page snapshot (the format of design-review's collect.js): what the
                    browser really showed, per viewport, theme and state. Best evidence.
  --source FOLDER   a scan of .html, .jsx, .tsx, .vue, .svelte and .astro files. Weaker:
                    strings put together at run time are not seen.
  --strings FILE    a JSON list of {"text", "role", "where"} written by hand or by a tool.

Blocks: one action called by two names, a button or link that does not say what happens,
an error that says what went wrong but gives no way forward, internal error text shown to
the user, and leftover placeholder text. Warnings (taste, never block): mixed capital
styles, shouting, weak labels, one destination with several link names.
A flagged string can be answered in an answers file: text, rule and a reason.

Exit codes: 0 = no blocking string left unanswered
            1 = at least one blocking string
            2 = not verified or blocked: no strings found, unreadable input, a bad answers file
With --inventory the full list of strings is written to a new JSON file. Nothing else is written.
"""
import argparse
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
RULES = HERE.parent / "references" / "copy-rules.json"
SOURCE_EXT = {".html", ".htm", ".jsx", ".tsx", ".vue", ".svelte", ".astro"}
SKIP_DIRS = {"node_modules", ".git", "dist", "build", ".next", "out", "coverage", "vendor", ".mstack", ".testrun"}
ACTION_ROLES = {"button", "link", "menuitem", "tab"}
PLACEHOLDER = [
    (re.compile(r"lorem ipsum|dolor sit amet|consectetur adipisc", re.I), "filler Latin"),
    (re.compile(r"\b(TODO|FIXME|TBD|XXX)\b"), "a work marker"),
    (re.compile(r"\b(placeholder|dummy|sample) (text|copy|title|heading|content|data)\b", re.I), "placeholder wording"),
    (re.compile(r"\b(your|insert|add) [\w ]{0,24}\bhere\b|\bgoes here\b", re.I), "placeholder wording"),
    (re.compile(r"\{\{[^{}]*\}\}|\[object Object\]"), "a value that was never filled in"),
    (re.compile(r"^(undefined|null|NaN|untitled|heading|subtitle|button text|link text)$", re.I), "a default or empty value shown as text"),
]
ERROR = re.compile(r"\b(error|failed|failure|could ?n[o'’]t|cannot|can[’']t|unable to|invalid|went wrong|not found|denied|expired|unavailable|oops|not allowed|rejected|timed out)\b", re.I)
RAW = re.compile(r"\b[A-Z][A-Za-z]+(Error|Exception)\b|\bE[A-Z]{4,}\b|\b(status|code|errno)[ :=]+-?\d{3,}\b|\b[45]\d\d (Internal|Bad|Not Found|Forbidden|Unauthorized|Service)\b|\bat [\w$.]+ \(|\b[Nn]ull pointer\b|\bundefined is not\b|\b[Ss]tack trace\b|0x[0-9a-fA-F]{4,}")
TAG_TEXT = re.compile(r"<(button|a|h[1-6]|label|p|span|div|li|option|th|td|summary|legend|small|strong|em|Button|Link|NavLink)\b([^<>]*)>([^<>{}]*[A-Za-z][^<>{}]*)<", re.S)
ATTR_TEXT = re.compile(r"\b(aria-label|placeholder|alt)\s*=\s*(?:\"([^\"{}<>]+)\"|'([^'{}<>]+)')")


class BadInput(Exception):
    pass


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def norm(text):
    return re.sub(r"[\s.…!:›»→>]+$", "", clean(text).lower())


# ---------- snapshot reader (format 1; the same reader is repeated in design-review and a11y-audit) ----------

def load_json(path):
    try:
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        if isinstance(data, str):  # some browser tools hand back the JSON as a quoted string
            data = json.loads(data)
    except (OSError, ValueError) as exc:
        raise BadInput(f"cannot read {path}: {exc}")
    return data


def views_of(data, path):
    if isinstance(data, dict) and isinstance(data.get("views"), list):
        views = data["views"]
    elif isinstance(data, dict) and "elements" in data:
        views = [data]
    else:
        raise BadInput(f"{path} is not a snapshot: it has neither 'views' nor 'elements'")
    for view in views:
        width = (view.get("viewport") or {}).get("width") if isinstance(view, dict) else None
        if not isinstance(width, (int, float)) or not isinstance(view.get("elements"), list):
            raise BadInput(f"{path}: every view needs viewport.width and a list of elements")
    return views


def label_of(view):
    return f"{view['viewport']['width']:g}/{view.get('theme', 'light')}/{view.get('state', 'default')}"


# ---------- gathering strings ----------

def beside(message, action):
    """An action belongs to a message when both sit in the same container, or the action is directly under it."""
    parent = (message.get("selector") or "").rpartition(" > ")[0]
    if parent and (action.get("selector") or "").startswith(parent + " > "):
        return True
    m, a = message["box"], action["box"]
    gap = a.get("y", 0) - (m.get("y", 0) + m.get("height", 0))
    return 0 <= gap <= 48 and a.get("x", 0) < m.get("x", 0) + m.get("width", 0) and m.get("x", 0) < a.get("x", 0) + a.get("width", 0)


def from_snapshot(path):
    out = []
    for view in views_of(load_json(path), path):
        actions = [e for e in view["elements"] if (e.get("role") or "") in ACTION_ROLES and e.get("box")]
        for el in view["elements"]:
            role = el.get("role") or ""
            where = f"{label_of(view)} {el.get('selector', '?')}"
            if role in ACTION_ROLES:
                text = clean(el.get("name") or el.get("text"))
            else:
                text = clean(el.get("text"))
            if text:
                item = {"text": text, "role": role or "text", "where": where}
                if el.get("href"):
                    item["href"] = el["href"]
                if role not in ACTION_ROLES and el.get("box"):
                    item["near"] = [clean(a.get("name") or a.get("text")) for a in actions if beside(el, a)]
                out.append(item)
            if el.get("placeholder"):
                out.append({"text": clean(el["placeholder"]), "role": "placeholder", "where": where})
    return out


def from_source(folder):
    root = pathlib.Path(folder)
    if not root.is_dir():
        raise BadInput(f"not a folder: {root}")
    out = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SOURCE_EXT:
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts[:-1]):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        text = re.sub(r"<!--.*?-->|\{/\*.*?\*/\}", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
        text = re.sub(r"<(script|style)\b.*?</\1>", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S | re.I)
        rel = path.relative_to(root)
        for m in TAG_TEXT.finditer(text):
            tag, attrs, body = m.group(1), m.group(2), clean(m.group(3))
            if not body or re.search(r"=>|;\s*$|\(\)", body):
                continue
            lower = tag.lower()
            role = "button" if lower == "button" else "link" if lower in ("a", "link", "navlink") else "heading" if re.fullmatch(r"h[1-6]", lower) else "text"
            explicit = re.search(r"role\s*=\s*[\"'](\w+)[\"']", attrs)
            if explicit:
                role = explicit.group(1)
            elif re.search(r"class(Name)?\s*=\s*[\"'][^\"']*\b(error|alert|danger|invalid)\b", attrs):
                role = "alert"
            item = {"text": body, "role": role, "where": f"{rel}:{text.count(chr(10), 0, m.start(3)) + 1}"}
            href = re.search(r"\b(?:href|to)\s*=\s*[\"']([^\"']+)[\"']", attrs)
            if href:
                item["href"] = href.group(1)
            out.append(item)
        for m in ATTR_TEXT.finditer(text):
            value = clean(m.group(2) or m.group(3))
            if value:
                out.append({"text": value, "role": "placeholder" if m.group(1) == "placeholder" else "label",
                            "where": f"{rel}:{text.count(chr(10), 0, m.start()) + 1}"})
    return out


def from_strings(path):
    data = load_json(path)
    if isinstance(data, dict):
        data = data.get("strings")
    if not isinstance(data, list):
        raise BadInput(f"{path} must hold a JSON list of strings")
    out = []
    for i, entry in enumerate(data):
        if not isinstance(entry, dict) or not clean(str(entry.get("text", ""))):
            raise BadInput(f"{path}: entry {i + 1} has no text")
        item = {"text": clean(str(entry["text"])), "role": entry.get("role") or "text", "where": str(entry.get("where") or f"entry {i + 1}")}
        for key in ("href", "near"):
            if entry.get(key):
                item[key] = entry[key]
        out.append(item)
    return out


# ---------- rules ----------

def judge(strings, rules):
    findings = []

    def add(level, rule, item, detail):
        findings.append({"level": level, "rule": rule, "text": item["text"], "where": item["where"], "detail": detail})

    vague = {v.lower() for v in rules["vague_action_labels"]}
    vague_links = {v.lower() for v in rules["vague_link_labels"]}
    weak = {v.lower() for v in rules["weak_action_labels"]}
    no_exit = {v.lower() for v in rules["labels_that_are_not_a_way_forward"]}
    recovery = re.compile(r"\b(" + "|".join(rules["recovery_cues"]) + r")\b", re.I)
    sets = [sorted((m.lower() for m in group), key=len, reverse=True) for group in rules["same_action_words"]]
    seen, by_key, by_set, by_href = set(), {}, {}, {}
    actions = []
    for item in strings:
        role, text, low = item["role"], item["text"], norm(item["text"])
        mark = (low, role)
        first = mark not in seen
        seen.add(mark)
        if first:
            for pattern, what in PLACEHOLDER:
                if pattern.search(text):
                    add("block", "placeholder", item, what)
                    break
        if role in ACTION_ROLES:
            actions.append(item)
            if first:
                if low in vague or (role == "link" and low in vague_links):
                    add("block", "vague-button", item, f"'{text}' does not say what will happen; name the action and its object")
                elif low in weak:
                    add("warn", "weak-label", item, f"'{text}' is fine in a known sequence, weak on its own")
                if len(text) > 3 and text.upper() == text and re.search(r"[A-Z]{2}", text) and " " in text:
                    add("warn", "shouting", item, "written in capitals")
            for index, group in enumerate(sets):
                member = next((m for m in group if re.search(r"(?<![\w-])" + re.escape(m) + r"(?![\w-])", low)), None)
                if member:
                    frame = re.sub(r"(?<![\w-])" + re.escape(member) + r"(?![\w-])", "{}", low, count=1)
                    frame = clean(re.sub(r"\b(the|a|an|your|my|this|to)\b", " ", frame))
                    by_key.setdefault((index, frame), {}).setdefault(member, item)
                    by_set.setdefault(index, {}).setdefault(member, item)
                    break
            href = item.get("href")
            if role == "link" and href and not href.startswith(("#", "javascript:", "mailto:", "tel:")):
                by_href.setdefault(href.rstrip("/") or "/", {}).setdefault(low, item)
        elif role != "placeholder" and first:
            if RAW.search(text):
                add("block", "raw-error", item, "internal error text is shown to the user; say what happened in their words")
            elif role in ("alert", "error") or (role in ("text", "status") and ERROR.search(text)):
                near = [n for n in item.get("near", []) if norm(n) and norm(n) not in no_exit and norm(n) not in vague]
                if not recovery.search(text) and not near:
                    add("block", "dead-end-error", item, "says what went wrong but not what the user can do next")
                elif "!" in text:
                    add("warn", "shouting", item, "an exclamation mark in an error message")
    blocked_sets = set()
    for (index, frame), members in by_key.items():
        if len(members) > 1:
            blocked_sets.add(index)
            names = "; ".join(f"'{it['text']}' ({it['where']})" for it in members.values())
            add("block", "mixed-names", next(iter(members.values())), f"one action, {len(members)} names: {names}. Pick one and use it everywhere")
    for index, members in by_set.items():
        if len(members) > 1 and index not in blocked_sets:
            names = "; ".join(f"'{it['text']}' ({it['where']})" for it in members.values())
            add("warn", "mixed-words", next(iter(members.values())), f"two words for one kind of action: {names}. Keep both only if they do different things")
    for href, labels in by_href.items():
        if len(labels) > 1:
            names = ", ".join(f"'{it['text']}'" for it in labels.values())
            add("warn", "one-target-many-names", next(iter(labels.values())), f"links to {href} are called {names}")
    title, sentence = set(), set()
    for label in {a["text"] for a in actions}:
        rest = label.split()[1:]
        if not rest or not label[:1].isupper():
            continue
        caps = sum(1 for w in rest if w[:1].isupper())
        lowers = sum(1 for w in rest if len(w) >= 4 and w[:1].islower())
        if caps and not lowers:
            title.add(label)
        elif not caps:
            sentence.add(label)
    if title and sentence and min(len(title), len(sentence)) >= 2:
        findings.append({"level": "warn", "rule": "mixed-case", "text": sorted(title)[0], "where": "all action labels",
                         "detail": f"{len(title)} labels in Title Case (such as '{sorted(title)[0]}') and {len(sentence)} in sentence case (such as '{sorted(sentence)[0]}')"})
    return findings


def load_answers(path):
    data = load_json(path)
    if not isinstance(data, list):
        raise BadInput(f"{path} must hold a JSON list")
    for entry in data:
        if not isinstance(entry, dict) or not entry.get("text") or not entry.get("rule"):
            raise BadInput(f"{path}: an answer needs text and rule: {json.dumps(entry)}")
        if len(str(entry.get("reason", "")).strip()) < 8:
            raise BadInput(f"{path}: an answer needs a reason of at least 8 characters: {json.dumps(entry)}")
    return data


def cmd_check(args):
    data = json.loads(RULES.read_text(encoding="utf-8"))
    rules = {k: v["value"] for k, v in data.items() if isinstance(v, dict)}
    try:
        if args.snapshot:
            strings, evidence = from_snapshot(args.snapshot), "rendered page snapshot"
        elif args.source:
            strings, evidence = from_source(args.source), "source scan (strings put together at run time are not seen)"
        else:
            strings, evidence = from_strings(args.strings), "strings file"
        answers = load_answers(args.answers) if args.answers else []
        if args.inventory and pathlib.Path(args.inventory).exists():
            raise BadInput(f"{args.inventory} already exists and this script does not overwrite files")
    except BadInput as exc:
        print(str(exc))
        print(f"RESULT not verified: {exc}")
        return 2
    if not strings:
        print("no visible strings were found, so there is nothing to judge")
        print("RESULT not verified: no strings found")
        return 2
    findings = judge(strings, rules)
    used = set()
    for f in findings:
        for i, a in enumerate(answers):
            if a["rule"] == f["rule"] and norm(a["text"]) == norm(f["text"]) and f["level"] == "block":
                f["level"], f["answer"] = "answered", a["reason"]
                used.add(i)
                break
    distinct = len({(norm(s["text"]), s["role"]) for s in strings})
    print(f"evidence: {evidence}")
    print(f"{len(strings)} strings read, {distinct} distinct, {sum(1 for s in strings if s['role'] in ACTION_ROLES)} action labels")
    order = {"block": 0, "answered": 1, "warn": 2}
    tag = {"block": "BLOCK", "answered": "answered", "warn": "warn"}
    for f in sorted(findings, key=lambda f: (order[f["level"]], f["rule"])):
        extra = f"  [answer: {f['answer']}]" if f.get("answer") else ""
        print(f"{tag[f['level']]:8} {f['rule']:22} \"{f['text'][:70]}\" at {f['where']}: {f['detail']}{extra}")
    for i, a in enumerate(answers):
        if i not in used:
            print(f"note: answer matched nothing and can be removed: {json.dumps(a)}")
    blocks = [f for f in findings if f["level"] == "block"]
    warns = [f for f in findings if f["level"] == "warn"]
    print(f"{len(blocks)} blocking, {len(used)} answered, {len(warns)} warnings (taste; the word lists were written on {data.get('_written', 'an unknown date')})")
    print("not seen by this check: tone, whether a label is true, text inside images, and states that were not captured or scanned")
    if args.inventory:
        rows = {}
        for s in strings:
            row = rows.setdefault((norm(s["text"]), s["role"]), {"text": s["text"], "role": s["role"], "count": 0, "where": []})
            row["count"] += 1
            if len(row["where"]) < 5:
                row["where"].append(s["where"])
        for f in findings:
            for row in rows.values():
                if norm(row["text"]) == norm(f["text"]):
                    row.setdefault("findings", []).append({"rule": f["rule"], "level": f["level"], "detail": f["detail"]})
        pathlib.Path(args.inventory).write_text(json.dumps({"evidence": evidence, "strings": list(rows.values())}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"inventory written to {args.inventory}")
    if blocks:
        print(f"RESULT fail: {len(blocks)} string(s) to fix or answer: {', '.join(sorted({f['rule'] for f in blocks}))}")
        return 1
    print("RESULT pass")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("check", help="judge the strings of an interface")
    where = p.add_mutually_exclusive_group(required=True)
    where.add_argument("--snapshot", help="page snapshot JSON (format 1)")
    where.add_argument("--source", help="folder of markup files to scan")
    where.add_argument("--strings", help="JSON list of {text, role, where}")
    p.add_argument("--answers", help="JSON list of answered findings: text, rule, reason")
    p.add_argument("--inventory", help="write every string with its role, places and findings to this new JSON file")
    args = parser.parse_args()
    return cmd_check(args)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Prove a copy-edit changed only what its list of changes says, and nothing that must not change.

  rules   list the rule ids of a style guide (default: references/house-style.md)
  check   compare the original and the edited text with the list of changes

The list of changes is a JSON file:
  {"guide": "house-style", "items": [
     {"category": "correction", "rule": "H6", "before": "recieve", "after": "receive"},
     {"category": "suggestion", "rule": "H2", "before": "...", "after": "...", "applied": false},
     {"category": "query", "before": "in 2019 we", "note": "The table says 2018. Which is right?"}]}
Corrections are applied. Suggestions are applied only when "applied" is true (the author accepted them).
Queries are never applied. "before" must be text from the original, long enough to be found once.

check runs four tests and reports counts by category:
  1. protected spans (code, quoted text, links and web addresses) are identical in both texts
  2. every number and every name (capitalised word not starting a sentence, or an all-capitals word) in the
     original is still in the edited text, unless a listed change removes it
  3. every difference is a listed change: the listed changes applied to the original give exactly the edited text
  4. every correction cites a rule that exists in the guide
With --second, a list made by editing the edited text again: it must hold no corrections (one pass is enough).

Exit codes: 0 = pass, 1 = fail, 2 = not verified or blocked. The texts are only read.
"""
import argparse
import collections
import difflib
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
GUIDE = HERE.parent / "references" / "house-style.md"
PROTECTED = [("code block", re.compile(r"```.*?```", re.S)), ("code", re.compile(r"`[^`\n]+`")),
             ("link", re.compile(r"\[[^\]]*\]\([^)]+\)")), ("web address", re.compile(r"https?://[^\s)>\]]+")),
             ("quotation", re.compile(r"“[^”]*”|\"[^\"\n]{1,400}\""))]
NUMBER = re.compile(r"(?<![\w.])[-+]?\d[\d,.]*\d%?|(?<![\w.])\d%?")
STARTERS = re.compile(r"(^|[.!?:]\s+|\n\s*[-*#>\d.)]*\s*)$")


def end(code, line):
    print(line)
    return code


def read(path):
    try:
        return pathlib.Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        sys.exit(end(2, f"blocked: cannot read {path}: {exc}"))


def rule_ids(path):
    return re.findall(r"^##\s+([A-Za-z]+\d+[a-z]?)\b", read(path), re.M)


def spans(text):
    found = collections.Counter()
    for kind, pattern in PROTECTED:
        for m in pattern.finditer(text):
            found[(kind, m.group(0))] += 1
        text = pattern.sub(" ", text)
    return found


def names(text):
    for _, pattern in PROTECTED:
        text = pattern.sub(" ", text)
    out = collections.Counter()
    for m in re.finditer(r"\b[A-Z][\w'’-]*[A-Za-z0-9]|\b[A-Z]\b", text):
        word = m.group(0)
        if word.isupper() and len(word) > 1 or not STARTERS.search(text[:m.start()]):
            if word not in ("I",):
                out[word] += 1
    return out


def numbers(text):
    return collections.Counter(n.rstrip(".,") for n in NUMBER.findall(text))


def apply(original, items):
    """Apply the changes that should be in the edited text. Returns (text, faults)."""
    text, faults = original, []
    for n, item in enumerate(items, 1):
        cat = item.get("category")
        before = item.get("before", "")
        if cat == "query" or (cat == "suggestion" and not item.get("applied")):
            if before and before not in original:
                faults.append(f"item {n} ({cat}): its 'before' text is not in the original: '{before[:50]}'")
            continue
        if not before:
            faults.append(f"item {n} ({cat}): no 'before' text")
            continue
        hits = text.count(before)
        if hits == 0:
            faults.append(f"item {n} ({cat}): '{before[:50]}' is not in the original (or an earlier item already changed it)")
        elif hits > 1 and not item.get("all"):
            faults.append(f"item {n} ({cat}): '{before[:50]}' appears {hits} times; quote more text so it is found once, or set \"all\": true")
        else:
            text = text.replace(before, item.get("after", ""))
    return text, faults


def unlisted(expected, edited):
    a, b = expected.split(), edited.split()
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op != "equal":
            out.append(f"'{' '.join(a[i1:i2])[:60] or '(nothing)'}' became '{' '.join(b[j1:j2])[:60] or '(nothing)'}'")
    return out


def cmd_rules(args):
    ids = rule_ids(args.guide)
    print(f"{args.guide}: {len(ids)} rules: {', '.join(ids)}")
    return end(0 if ids else 2, "RESULT pass" if ids else "blocked: no '## <id> <title>' headings found in the guide")


def cmd_check(args):
    original, edited = read(args.original), read(args.edited)
    try:
        items = json.loads(read(args.changes))["items"]
        assert isinstance(items, list) and all(isinstance(i, dict) for i in items)
    except (ValueError, KeyError, AssertionError) as exc:
        return end(2, f"blocked: {args.changes} is not a list of changes ({exc!r}); see --help for the format")
    ids = set(rule_ids(args.guide))
    faults = []
    counts = collections.Counter(i.get("category", "?") for i in items)
    bad = [i for i in items if i.get("category") not in ("correction", "suggestion", "query")]
    if bad:
        faults.append(f"{len(bad)} item(s) have a category other than correction, suggestion or query")
    for n, item in enumerate(items, 1):
        if item.get("category") == "correction":
            if not item.get("rule"):
                faults.append(f"item {n}: a correction with no rule; without a rule it is a suggestion")
            elif ids and item["rule"] not in ids:
                faults.append(f"item {n}: rule '{item['rule']}' is not in {pathlib.Path(args.guide).name}")
        if item.get("category") == "query" and item.get("applied"):
            faults.append(f"item {n}: a query was marked applied; queries go to the author and change nothing")

    lost = spans(original) - spans(edited)
    for (kind, text), k in lost.items():
        faults.append(f"protected {kind} changed or gone: {text[:60]!r}" + (f" ({k} times)" if k > 1 else ""))
    removed = " ".join(i.get("before", "") for i in items if i.get("category") != "query")
    added = " ".join(i.get("after", "") for i in items if i.get("category") != "query")
    for label, fn in (("number", numbers), ("name", names)):
        missing = fn(original) - fn(edited)
        for token, k in missing.items():
            if fn(removed)[token] - fn(added)[token] >= k:
                continue  # a listed change removed it on purpose
            faults.append(f"{label} '{token}' from the original is missing in the edited text" + (f" ({k} of them)" if k > 1 else ""))
    expected, apply_faults = apply(original, items)
    faults += apply_faults
    diffs = unlisted(expected, edited) if not apply_faults else []
    faults += [f"change not in the list: {d}" for d in diffs[:20]]
    if args.second:
        try:
            again = json.loads(read(args.second))["items"]
        except (ValueError, KeyError) as exc:
            return end(2, f"blocked: {args.second} is not a list of changes ({exc!r})")
        more = [i for i in again if i.get("category") == "correction"]
        if more:
            faults.append(f"a second pass over the edited text found {len(more)} new correction(s); the first pass missed them or caused them")
    print(f"guide: {pathlib.Path(args.guide).name} ({len(ids)} rules)")
    print(f"items: {counts.get('correction', 0)} corrections, {counts.get('suggestion', 0)} suggestions "
          f"({sum(1 for i in items if i.get('category') == 'suggestion' and i.get('applied'))} accepted), {counts.get('query', 0)} queries")
    by_rule = collections.Counter(i.get("rule") for i in items if i.get("category") == "correction")
    if by_rule:
        print("corrections by rule: " + ", ".join(f"{r} {k}" for r, k in sorted(by_rule.items(), key=lambda x: str(x[0]))))
    print(f"protected spans in the original: {sum(spans(original).values())}; numbers: {sum(numbers(original).values())}; names: {sum(names(original).values())}")
    for f in faults[:30]:
        print("  FAIL " + f)
    if faults:
        return end(1, f"RESULT fail: {len(faults)} problem(s); first: {faults[0]}")
    note = "" if args.second else "; no second pass was given, so 'one pass is enough' was not checked"
    return end(0, f"RESULT pass: every difference is a listed change and nothing protected moved{note}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--guide", type=pathlib.Path, default=GUIDE, help="style guide with '## <id> <title>' rule headings")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("rules", help="list the guide's rule ids")
    p = sub.add_parser("check", help="check an edit against its list of changes")
    p.add_argument("original", type=pathlib.Path)
    p.add_argument("edited", type=pathlib.Path)
    p.add_argument("--changes", type=pathlib.Path, required=True, help="the list of changes (JSON)")
    p.add_argument("--second", type=pathlib.Path, help="list of changes from a second pass over the edited text")
    args = parser.parse_args()
    return {"rules": cmd_rules, "check": cmd_check}[args.action](args)


if __name__ == "__main__":
    sys.exit(main())

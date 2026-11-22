#!/usr/bin/env python3
"""Prove a translation kept everything that must survive it. Translation quality itself is NOT checked.

  text     compare a source text file with its translation
  strings  compare a JSON strings file (flat or nested) with its translation, key by key

What must match, in count and exact form, between source and translation:
  numbers, web addresses, email addresses, placeholders ({name}, {{name}}, %s, %1$d, %(name)s, ${name}),
  markup tags (<b>, </a>, <br/>) and Markdown link targets.
With --glossary (JSON {"source term": "required translation"}), each term must appear as many times in the
translation as in the source. A term mapped to itself is a name that must not be translated.
For strings files: every source key has a non-empty translation; keys missing or added are listed; a
value left identical to the source is flagged; --limits (JSON {"key": max characters}) or --max-ratio
(translation length / source length) cap length for interface text.

Numbers must match in form, so 1,000 against 1.000 is reported. If the target language writes numbers
differently, say so to the user and pass --loose-numbers, which compares digits only.

Exit codes: 0 = pass, 1 = fail, 2 = not verified or blocked. Files are only read.
"""
import argparse
import collections
import json
import pathlib
import re
import sys

PATTERNS = [
    ("web address", re.compile(r"https?://[^\s<>\"')\]]+")),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("link target", re.compile(r"\]\(([^)\s]+)\)")),
    ("placeholder", re.compile(r"\{\{\s*\w+\s*\}\}|\$\{\w+\}|\{\w*(?:,[^{}]*)?\}|%\(\w+\)[sdif]|%\d+\$[sdif@]|%[sdif@]")),
    ("tag", re.compile(r"</?[A-Za-z][\w-]*(?:\s[^<>]*)?/?>")),
    ("number", re.compile(r"(?<![\w.])\d[\d,.  ]*\d|(?<![\w.])\d")),
]


PLURAL = {"web address": "web addresses", "email": "email addresses", "link target": "link targets",
          "placeholder": "placeholders", "tag": "tags", "number": "numbers"}


def end(code, line):
    print(line)
    return code


def load_json(path, what):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        sys.exit(end(2, f"blocked: cannot read the {what} {path}: {exc}"))


def tokens(text, loose):
    found = {}
    rest = text
    for kind, pattern in PATTERNS:
        items = [m.group(1) if pattern.groups else m.group(0) for m in pattern.finditer(rest)]
        if kind == "web address":
            items = [i.rstrip(".,;:") for i in items]
        if kind == "number" and loose:
            items = [re.sub(r"\D", "", i) for i in items]
        found[kind] = collections.Counter(items)
        rest = pattern.sub(" ", rest)
    return found


def compare(src, dst, glossary, loose, label=""):
    faults = []
    a, b = tokens(src, loose), tokens(dst, loose)
    for kind in a:
        if a[kind] != b[kind]:
            lost = list((a[kind] - b[kind]).elements())
            new = list((b[kind] - a[kind]).elements())
            faults.append(f"{label}{PLURAL[kind]} differ: " + "; ".join(x for x in (f"missing {lost}" if lost else "", f"added {new}" if new else "") if x))
    for term, wanted in glossary.items():
        n_src = len(re.findall(rf"(?<!\w){re.escape(term)}(?!\w)", src, re.I))
        n_dst = len(re.findall(rf"(?<!\w){re.escape(wanted)}(?!\w)", dst, re.I if wanted != term else 0))
        if n_src and n_dst < n_src:
            faults.append(f"{label}glossary: '{term}' appears {n_src} time(s) in the source; '{wanted}' appears {n_dst} time(s) in the translation")
    return faults, sum(sum(c.values()) for c in a.values())


def flatten(data, prefix=""):
    out = {}
    if isinstance(data, dict):
        for k, v in data.items():
            out.update(flatten(v, f"{prefix}{k}."))
    elif isinstance(data, list):
        for i, v in enumerate(data):
            out.update(flatten(v, f"{prefix}{i}."))
    else:
        out[prefix[:-1]] = data
    return out


def glossary_of(args):
    if not args.glossary:
        return {}
    data = load_json(args.glossary, "glossary")
    if not isinstance(data, dict) or not all(isinstance(v, str) for v in data.values()):
        sys.exit(end(2, 'blocked: the glossary must be a JSON object such as {"invoice": "Rechnung", "mstack": "mstack"}'))
    return data


def finish(faults, warnings, checked):
    for w in warnings[:20]:
        print("  warning: " + w)
    for f in faults[:40]:
        print("  FAIL " + f)
    print("not checked: whether the translation is accurate, natural or right in tone. A person who reads both languages has to judge that.")
    if faults:
        return end(1, f"RESULT fail: {len(faults)} problem(s); first: {faults[0]}")
    return end(0, f"RESULT pass: {checked} protected items match in count and form; translation quality was not checked")


def cmd_text(args):
    try:
        src = args.source.read_text(encoding="utf-8")
        dst = args.translation.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return end(2, f"blocked: {exc}")
    if not dst.strip():
        return end(1, "RESULT fail: the translation is empty")
    faults, checked = compare(src, dst, glossary_of(args), args.loose_numbers)
    warnings = []
    if src.strip() == dst.strip():
        warnings.append("the translation is identical to the source")
    ratio = len(dst) / max(1, len(src))
    print(f"source {len(src)} characters, translation {len(dst)} (ratio {ratio:.2f})")
    if args.max_ratio and ratio > args.max_ratio:
        faults.append(f"translation is {ratio:.2f} times the source length; the limit is {args.max_ratio}")
    return finish(faults, warnings, checked)


def cmd_strings(args):
    src = flatten(load_json(args.source, "source strings file"))
    dst = flatten(load_json(args.translation, "translated strings file"))
    limits = load_json(args.limits, "limits file") if args.limits else {}
    glossary = glossary_of(args)
    faults, warnings, checked = [], [], 0
    for key, value in src.items():
        if not isinstance(value, str):
            continue
        got = dst.get(key)
        if got is None:
            faults.append(f"{key}: no translation")
            continue
        if not isinstance(got, str) or not got.strip():
            faults.append(f"{key}: translation is empty")
            continue
        more, n = compare(value, got, glossary, args.loose_numbers, f"{key}: ")
        faults += more
        checked += n
        if got == value and re.search(r"[A-Za-z]{3}", value):
            warnings.append(f"{key}: identical to the source (untranslated, or a name that stays the same)")
        cap = limits.get(key)
        if cap is not None and len(got) > cap:
            faults.append(f"{key}: {len(got)} characters, limit {cap}: '{got[:40]}'")
        if args.max_ratio and len(value) >= 4 and len(got) / len(value) > args.max_ratio:
            faults.append(f"{key}: {len(got) / len(value):.2f} times the source length (limit {args.max_ratio})")
    extra = sorted(set(dst) - set(src))
    if extra:
        warnings.append(f"{len(extra)} key(s) in the translation are not in the source: {', '.join(extra[:5])}")
    for key in limits:
        if key not in src:
            warnings.append(f"limits file names '{key}', which is not in the source")
    print(f"keys: {len(src)} in the source, {len(dst)} in the translation, {sum(1 for k in src if k in dst)} matched")
    return finish(faults, warnings, checked)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("text", "strings"):
        p = sub.add_parser(name)
        p.add_argument("source", type=pathlib.Path)
        p.add_argument("translation", type=pathlib.Path)
        p.add_argument("--glossary", type=pathlib.Path, help='JSON {"source term": "required translation"}')
        p.add_argument("--max-ratio", type=float, help="longest allowed translation, as a multiple of the source length")
        p.add_argument("--loose-numbers", action="store_true", help="compare the digits of numbers only (the user agreed the target writes numbers differently)")
        if name == "strings":
            p.add_argument("--limits", type=pathlib.Path, help='JSON {"key": max characters}')
    args = parser.parse_args()
    return {"text": cmd_text, "strings": cmd_strings}[args.action](args)


if __name__ == "__main__":
    sys.exit(main())

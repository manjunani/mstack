#!/usr/bin/env python3
"""Describe a CSV file, a JSON-lines file or one SQLite table as it really is. Read-only.

  profile.py <file> [--table NAME] [--top 5] [--max-rows N] [--json NEW_FILE] [--show-personal]

Prints, for the whole dataset: real file type, encoding, row and column counts, exact duplicate rows.
Per column: inferred type (decided value by value), share of empty values, distinct count, min and max
(or shortest and longest text), the most common values, and whether the column looks like an identifier
or like personal data. Top values of personal-data columns are hidden unless --show-personal is given.

The report keeps three lists apart: findings, checked and fine, could not check.
Exit codes: 0 = profile made, nothing structurally broken (warnings may be listed)
            1 = a structural fault: no data rows, rows with the wrong number of fields, lines that do not parse
            2 = not verified or blocked: unreadable file, table not named, rows left unread
The input is never changed. --json writes the full profile to a new file and refuses to overwrite.
"""
import argparse
import collections
import csv
import io
import json
import os
import pathlib
import re
import sqlite3
import sys
import urllib.parse

# --- shared block: report (the same text is in every mstack-data script) ---
class Report:
    """Keeps three lists apart: findings, checked and fine, could not check."""

    def __init__(self):
        self.fails, self.warns, self.fine, self.unchecked = [], [], [], []

    def fail(self, text):
        self.fails.append(text)

    def warn(self, text):
        self.warns.append(text)

    def ok(self, text):
        self.fine.append(text)

    def skip(self, text):
        self.unchecked.append(text)

    def as_dict(self):
        return {"findings": [{"level": "fail", "text": t} for t in self.fails] + [{"level": "warn", "text": t} for t in self.warns],
                "checked_and_fine": self.fine, "could_not_check": self.unchecked}

    def show(self):
        print(f"\nFINDINGS ({len(self.fails) + len(self.warns)})")
        for text in self.fails:
            print(f"  [fail] {text}")
        for text in self.warns:
            print(f"  [warn] {text}")
        print(f"\nCHECKED AND FINE ({len(self.fine)})")
        for text in self.fine:
            print(f"  {text}")
        print(f"\nCOULD NOT CHECK ({len(self.unchecked)})")
        for text in self.unchecked:
            print(f"  {text}")
        print()

    def finish(self, why=None):
        """Print the three lists and the RESULT line; return the exit code."""
        self.show()
        if self.fails:
            print(f"RESULT fail: {why or self.fails[0]}" + (f" (and {len(self.fails) - 1} more)" if len(self.fails) > 1 and not why else ""))
            return 1
        if self.unchecked:
            more = f" (and {len(self.unchecked) - 1} more)" if len(self.unchecked) > 1 else ""
            print(f"RESULT not verified: {self.unchecked[0]}{more}")
            return 2
        if self.warns:
            print(f"{len(self.warns)} warning(s) above do not block; report them with the result.")
        print("RESULT pass")
        return 0


def blocked(text):
    print(f"blocked: {text}")
    sys.exit(2)
# --- end of shared block ---

# --- shared block: table loader (the same text is in every mstack-data script that reads a dataset) ---
SQLITE_MAGIC = b"SQLite format 3\x00"


class Blocked(Exception):
    """The script cannot go on without the user."""


def sniff_kind(path):
    """Decide the real file type from its first bytes, not from its extension."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(4096)
    except OSError as exc:
        raise Blocked(f"cannot read {path}: {exc.strerror}")
    if not head.strip():
        raise Blocked(f"{path} is empty")
    if head.startswith(SQLITE_MAGIC):
        return "sqlite"
    if head.startswith(b"PK\x03\x04"):
        raise Blocked(f"{path} is a zip container such as .xlsx; export the sheet to CSV first")
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        raise Blocked(f"{path} is an old binary Office file; save it as CSV first")
    text = head.decode("utf-8", "replace").lstrip("﻿ \t\r\n")
    if text.startswith("{"):
        return "jsonl"
    if text.startswith("["):
        return "json"
    return "csv"


def _flat(value):
    return json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else value


def _records(records, max_rows, notes):
    if max_rows and len(records) > max_rows:
        records, notes["truncated"] = records[:max_rows], True
    seen = {}
    for record in records:
        for key in record:
            seen.setdefault(key, None)
    columns = list(seen)
    return columns, [[_flat(record.get(c)) for c in columns] for record in records]


def load_table(path, table=None, max_rows=None):
    """Return (kind, columns, rows, notes). Each row is a list; an absent value is None.
    Row n in every report is the n-th data row: the header line is not counted."""
    kind = sniff_kind(path)
    notes = {"ragged": [], "bad_lines": [], "encoding": "utf-8", "truncated": False, "renamed": [], "table": table}
    if kind == "sqlite":
        uri = "file:" + urllib.parse.quote(os.path.abspath(path)) + "?mode=ro"
        try:
            conn = sqlite3.connect(uri, uri=True)
            names = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        except sqlite3.Error as exc:
            raise Blocked(f"cannot open {path} read-only: {exc}")
        if table is None:
            if len(names) != 1:
                raise Blocked(f"{path} holds {len(names)} tables ({', '.join(names) or 'none'}); name one with --table")
            table = names[0]
        if table not in names:
            raise Blocked(f"no table '{table}' in {path}; it holds: {', '.join(names) or 'none'}")
        notes["table"] = table
        cursor = conn.execute('SELECT * FROM "' + table.replace('"', '""') + '"')
        columns, rows = [d[0] for d in cursor.description], []
        for row in cursor:
            if max_rows and len(rows) >= max_rows:
                notes["truncated"] = True
                break
            rows.append(list(row))
        conn.close()
        return kind, columns, rows, notes
    with open(path, "rb") as handle:
        raw = handle.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text, notes["encoding"] = raw.decode("latin-1"), "latin-1 (the file is not valid UTF-8)"
    if kind == "json":
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise Blocked(f"{path} starts like a JSON array but does not parse: {exc}")
        if not all(isinstance(item, dict) for item in data):
            raise Blocked(f"{path} is a JSON array, but not every item is an object")
        columns, rows = _records(data, max_rows, notes)
        return kind, columns, rows, notes
    if kind == "jsonl":
        records = []
        for number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                record = None
            if isinstance(record, dict):
                records.append(record)
            else:
                notes["bad_lines"].append(number)
        columns, rows = _records(records, max_rows, notes)
        return kind, columns, rows, notes
    first = text.split("\n", 1)[0]
    delimiter = max(",;\t|", key=lambda d: (first.count(d), d == ","))
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    columns, rows = [], []
    for position, name in enumerate(next(reader, []), 1):
        name = name.strip() or f"column_{position}"
        if name in columns:
            notes["renamed"].append(name)
            name = f"{name}__{position}"
        columns.append(name)
    for row in reader:
        if not row or (len(row) == 1 and not row[0].strip()):
            continue
        if max_rows and len(rows) >= max_rows:
            notes["truncated"] = True
            break
        if len(row) != len(columns):
            notes["ragged"].append(len(rows) + 1)
            row = (row + [""] * len(columns))[:len(columns)]
        rows.append(row)
    return kind, columns, rows, notes


def is_empty(value):
    return value is None or (isinstance(value, str) and value.strip() == "")


def as_number(value):
    """Return a float for a number or numeric text, or None."""
    if isinstance(value, bool) or is_empty(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        number = float(str(value).strip().replace(",", ""))
    except ValueError:
        return None
    return number if number == number and abs(number) != float("inf") else None


def brief(numbers, limit=12):
    """A short, readable list of row numbers."""
    numbers = list(numbers)
    shown = ", ".join(str(n) for n in numbers[:limit])
    return shown + (f" and {len(numbers) - limit} more" if len(numbers) > limit else "")
# --- end of shared block ---

LIMITS_FILE = pathlib.Path(__file__).resolve().parent.parent / "references" / "limits.json"
FALLBACK = {"near_unique_share": 0.9, "high_empty_share": 0.5, "personal_value_share": 0.5, "max_rows": 500000}
BLANK_WORDS = {"n/a", "na", "null", "none", "nil", "nan", "-", "--", "?", "#n/a"}
INT = re.compile(r"[+-]?\d+$")
FLOAT = re.compile(r"[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$")
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}$")
ISO_TIME = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$")
OTHER_DATE = re.compile(r"\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}$")
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
PHONE = re.compile(r"(\+\d[\d\s().-]{7,}|\(?\d{2,4}\)?[\s.-]\d{2,4}[\s.-]\d{2,6}([\s.-]\d{1,6})?)$")
IPV4 = re.compile(r"(\d{1,3}\.){3}\d{1,3}$")
ID_NAME = re.compile(r"(^|[_\s-])(id|uuid|guid|key|sku)$|[a-z]Id$|^id$", re.I)
PERSONAL_NAME = re.compile(
    r"e-?mail|phone|mobile|(^|_)tel(_|$)|(first|last|full|sur|user|customer|patient|employee)[_\s-]?name|address|street|"
    r"post_?code|zip|(^|_)dob(_|$)|birth|ssn|passport|aadhaar|(^|_)pan(_|$)|iban|card_?(no|num)|salary|gender|(^|_)ip(_|$)", re.I)


def load_limits():
    """Thresholds come from references/limits.json so that they carry a source and a date."""
    limits, lines = dict(FALLBACK), []
    try:
        data = json.loads(LIMITS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return limits, [f"limits file not readable ({LIMITS_FILE.name}); built-in defaults used, unverified"]
    for name, entry in data.items():
        if name in limits and isinstance(entry, dict) and "value" in entry:
            limits[name] = entry["value"]
            if not entry.get("verified"):
                lines.append(f"{name} = {entry['value']} is an unverified default (checked {entry.get('checked', 'never')})")
    return limits, lines


def value_type(value):
    if value is None:
        return "empty"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, bytes):
        return "bytes"
    text = str(value).strip()
    if text == "":
        return "empty"
    if text.lower() in BLANK_WORDS:
        return "blank word"
    if INT.match(text):
        return "text" if len(text.lstrip("+-")) > 1 and text.lstrip("+-").startswith("0") else "int"
    if FLOAT.match(text):
        return "float"
    if ISO_TIME.match(text):
        return "datetime"
    if ISO_DATE.match(text):
        return "date"
    if OTHER_DATE.match(text):
        return "date (not ISO)"
    if text.lower() in ("true", "false"):
        return "bool"
    return "text"


FAMILY = {"int": "number", "float": "number", "date": "date", "datetime": "date"}


def profile_column(name, values, limits):
    total = len(values)
    types = collections.Counter(value_type(v) for v in values)
    empty = types.pop("empty", 0)
    blank_words = types.pop("blank word", 0)
    real = [(i, v) for i, v in enumerate(values, 1) if value_type(v) not in ("empty", "blank word")]
    families = collections.Counter()
    for kind, count in types.items():
        families[FAMILY.get(kind, kind)] += count
    main = families.most_common(1)[0][0] if families else "empty"
    if main == "number":
        shown = "float" if types.get("float") else "int"
    elif main == "date":
        shown = "datetime" if types.get("datetime") else "date"
    else:
        shown = main
    odd_rows = [i for i, v in real if FAMILY.get(value_type(v), value_type(v)) != main]
    texts = [str(v).strip() if isinstance(v, str) else v for _, v in real]
    counts = collections.Counter(texts)
    info = {"name": name, "type": shown, "rows": total, "empty": empty, "empty_share": round(empty / total, 4) if total else 0,
            "blank_words": blank_words, "distinct": len(counts), "other_type_rows": odd_rows,
            "padded": sum(1 for _, v in real if isinstance(v, str) and v != v.strip())}
    if main == "number":
        numbers = [as_number(v) for _, v in real if as_number(v) is not None]
        info["min"], info["max"] = (min(numbers), max(numbers)) if numbers else (None, None)
    elif main == "date":
        dates = sorted(str(v).strip() for _, v in real if value_type(v) in ("date", "datetime"))
        info["min"], info["max"] = (dates[0], dates[-1]) if dates else (None, None)
    elif real:
        lengths = [len(str(v)) for v in texts]
        info["shortest"], info["longest"] = min(lengths), max(lengths)
    repeats = sum(c - 1 for c in counts.values() if c > 1)
    info["repeated_values"] = repeats
    all_distinct = bool(counts) and repeats == 0 and empty == 0 and blank_words == 0 and total > 1
    named_id = bool(ID_NAME.search(name))
    info["identifier_like"] = named_id or (all_distinct and shown in ("int", "text"))
    info["identifier_reason"] = "name" if named_id else ("every value is distinct" if info["identifier_like"] else "")
    personal = []
    if PERSONAL_NAME.search(name):
        personal.append("column name")
    if counts and main == "text":
        strings = [str(v) for v in texts]
        for label, pattern in (("email", EMAIL), ("phone", PHONE), ("IP address", IPV4)):
            share = sum(1 for s in strings if pattern.match(s)) / len(strings)
            if share >= limits["personal_value_share"]:
                personal.append(f"{label} values, {share:.0%}")
    info["personal"] = personal
    info["top"] = [[str(value), count] for value, count in counts.most_common(5)]
    return info


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", help="a CSV, JSON-lines or SQLite file")
    parser.add_argument("--table", help="table or view name, for a SQLite file with more than one")
    parser.add_argument("--top", type=int, default=5, help="how many of the most common values to show per column (default 5, at most 5)")
    parser.add_argument("--max-rows", type=int, help="read at most this many rows (default from references/limits.json)")
    parser.add_argument("--json", dest="json_out", help="write the full profile to this NEW file")
    parser.add_argument("--show-personal", action="store_true", help="print top values even for columns that look like personal data")
    args = parser.parse_args()

    limits, limit_lines = load_limits()
    if args.json_out and os.path.exists(args.json_out):
        blocked(f"{args.json_out} already exists; choose a new file name")
    try:
        kind, columns, rows, notes = load_table(args.file, args.table, args.max_rows or limits["max_rows"])
    except Blocked as exc:
        blocked(str(exc))

    report = Report()
    where = f"{args.file}" + (f" table {notes['table']}" if kind == "sqlite" else "")
    print(f"PROFILE {where}")
    print(f"  type {kind}, encoding {notes['encoding'] if kind != 'sqlite' else 'n/a'}, {len(rows)} rows, {len(columns)} columns")
    print("  row numbers below count data rows; the header line is not counted")
    for line in limit_lines:
        print(f"  note: {line}")

    if not rows:
        report.fail("no data rows: the file has a header or structure but nothing in it")
    if notes["ragged"]:
        report.fail(f"{len(notes['ragged'])} row(s) have the wrong number of fields: rows {brief(notes['ragged'])}")
    elif kind == "csv" and rows:
        report.ok(f"every row has {len(columns)} fields")
    if notes["bad_lines"]:
        report.fail(f"{len(notes['bad_lines'])} line(s) are not a JSON object: lines {brief(notes['bad_lines'])}")
    if notes["renamed"]:
        report.fail(f"column names repeat in the header: {', '.join(sorted(set(notes['renamed'])))}")
    if notes["encoding"] != "utf-8":
        report.warn(f"the file is not valid UTF-8; it was read as {notes['encoding']}, so some characters may be wrong")
    if notes["truncated"]:
        report.skip(f"rows after the first {len(rows)} were not read (--max-rows raises the limit)")

    seen = collections.Counter(tuple("" if v is None else str(v) for v in row) for row in rows)
    duplicate_rows = sum(c - 1 for c in seen.values() if c > 1)
    if duplicate_rows:
        first_seen, dup_numbers = set(), []
        for number, row in enumerate(rows, 1):
            key = tuple("" if v is None else str(v) for v in row)
            if key in first_seen:
                dup_numbers.append(number)
            first_seen.add(key)
        report.warn(f"{duplicate_rows} exact duplicate row(s): rows {brief(dup_numbers)}")
    elif rows:
        report.ok("no exact duplicate rows")

    profiles = []
    print("\nCOLUMNS")
    for index, name in enumerate(columns):
        info = profile_column(name, [row[index] for row in rows], limits)
        profiles.append(info)
        if "min" in info:
            spread = f"min {info['min']}  max {info['max']}"
        elif "shortest" in info:
            spread = f"length {info['shortest']} to {info['longest']}"
        else:
            spread = "no values"
        tags = []
        if info["identifier_like"]:
            tags.append(f"identifier-like ({info['identifier_reason']})")
        if info["personal"]:
            tags.append("personal data? (" + "; ".join(info["personal"]) + ")")
        print(f"  {index + 1}. {name}: {info['type']}, empty {info['empty_share']:.1%}, distinct {info['distinct']}, {spread}"
              + ("  | " + ", ".join(tags) if tags else ""))
        if info["personal"] and not args.show_personal:
            info["top"] = []
            print("     top: hidden, the column looks like personal data (--show-personal prints them)")
        elif info["distinct"] and info["repeated_values"] == 0:
            print("     top: every value appears once")
        elif info["top"]:
            print("     top: " + ", ".join(f"{value!r} x{count}" for value, count in info["top"][:max(1, min(args.top, 5))]))

        if info["other_type_rows"]:
            report.warn(f"column '{name}' is mostly {info['type']} but {len(info['other_type_rows'])} value(s) are another type: rows {brief(info['other_type_rows'])}")
        elif info["distinct"]:
            report.ok(f"column '{name}': one type ({info['type']})")
        if info["blank_words"]:
            report.warn(f"column '{name}' has {info['blank_words']} value(s) such as N/A, null or - that stand for missing; the empty share above does not count them")
        if info["type"] == "date (not ISO)":
            report.warn(f"column '{name}' holds dates that are not in ISO form; day and month order cannot be told from the values")
        if info["padded"]:
            report.warn(f"column '{name}' has {info['padded']} value(s) with spaces at the start or end")
        if info["empty_share"] >= limits["high_empty_share"] and rows:
            report.warn(f"column '{name}' is {info['empty_share']:.0%} empty")
        if info["identifier_like"] and info["repeated_values"] and info["distinct"] / max(1, info["rows"] - info["empty"]) >= limits["near_unique_share"]:
            report.warn(f"column '{name}' looks like an identifier but {info['repeated_values']} value(s) repeat")
        if info["personal"]:
            report.warn(f"column '{name}' looks like personal data ({'; '.join(info['personal'])}); think before sharing or uploading this file")

    if args.json_out:
        payload = {"file": args.file, "kind": kind, "table": notes["table"], "encoding": notes["encoding"], "rows": len(rows),
                   "duplicate_rows": duplicate_rows, "columns": profiles, **report.as_dict()}
        with open(args.json_out, "x", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, default=str)
        print(f"\nfull profile written to {args.json_out}")
    return report.finish()


if __name__ == "__main__":
    sys.exit(main())

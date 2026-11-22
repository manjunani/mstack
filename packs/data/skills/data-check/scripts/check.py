#!/usr/bin/env python3
"""Run a written set of rules against a dataset and report each rule with the rows that break it. Read-only.

  check.py <rules.json> [--max-show 20] [--quarantine NEW_FILE.csv]

The rules file names the dataset and lists the rules (see references/rules.md for every field):

  { "dataset": "orders.csv",
    "rules": [
      { "type": "not_null",    "column": "id" },
      { "type": "unique",      "columns": ["id"] },
      { "type": "in_set",      "column": "status", "values": ["new", "paid"] },
      { "type": "range",       "column": "amount", "min": 0, "max": 5000 },
      { "type": "pattern",     "column": "email", "regex": "[^@]+@[^@]+" },
      { "type": "row_count",   "min": 1, "max": 100000 },
      { "type": "foreign_key", "column": "customer_id", "ref": "customers.csv", "ref_column": "id" } ] }

A rule may carry "name" and "severity": "hard" (default, fails the run) or "soft" (warns).
Paths are relative to the rules file. A SQLite dataset is written as {"path": "db.sqlite", "table": "orders"}.
Zero data rows fails unless a row_count rule with "min": 0 says an empty dataset is allowed.

Exit codes: 0 = every hard rule passed
            1 = at least one hard rule failed
            2 = not verified or blocked: a rule could not run, or the rules file or dataset is unusable
--quarantine writes every failing row with the rule name to a new CSV file; the dataset is never changed.
"""
import argparse
import csv
import io
import json
import os
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

KNOWN = ("not_null", "unique", "in_set", "range", "pattern", "row_count", "foreign_key")


def resolve(base, spec):
    """Return (path, table) for a dataset written as a string or as {"path": ..., "table": ...}."""
    if isinstance(spec, dict):
        path, table = spec.get("path"), spec.get("table")
    else:
        path, table = spec, None
    if not isinstance(path, str) or not path:
        raise Blocked("a dataset needs a path")
    return (path if os.path.isabs(path) else os.path.join(base, path)), table


def run_rule(rule, columns, rows, base):
    """Return (state, detail, failing_rows). state is 'pass', 'fail' or 'not run'."""
    kind = rule.get("type")
    if kind not in KNOWN:
        return "not run", f"unknown rule type {kind!r}; known types: {', '.join(KNOWN)}", []
    if kind == "row_count":
        low, high = rule.get("min"), rule.get("max")
        if low is None and high is None:
            return "not run", "row_count needs min, max or both", []
        ok = (low is None or len(rows) >= low) and (high is None or len(rows) <= high)
        wanted = f"between {low if low is not None else 'any'} and {high if high is not None else 'any'}"
        return ("pass" if ok else "fail"), f"{len(rows)} rows, wanted {wanted}", []
    names = rule.get("columns") or ([rule["column"]] if rule.get("column") else [])
    if kind != "unique" and len(names) != 1:
        return "not run", f"{kind} needs exactly one column", []
    missing = [n for n in names if n not in columns]
    if not names or missing:
        return "not run", f"column(s) not in the dataset: {', '.join(missing) or 'none named'}", []
    index = [columns.index(n) for n in names]
    cells = [(number, row[index[0]]) for number, row in enumerate(rows, 1)]

    if kind == "not_null":
        bad = [n for n, v in cells if is_empty(v)]
        return ("fail" if bad else "pass"), f"{len(bad)} empty value(s)", bad
    if kind == "unique":
        first, bad = {}, []
        for number, row in enumerate(rows, 1):
            key = tuple("" if row[i] is None else str(row[i]).strip() for i in index)
            if all(part == "" for part in key):
                continue
            if key in first:
                bad.append(number)
            else:
                first[key] = number
        return ("fail" if bad else "pass"), f"{len(bad)} row(s) repeat an earlier key", bad
    if kind == "in_set":
        values = rule.get("values")
        if not isinstance(values, list) or not values:
            return "not run", "in_set needs a non-empty list in 'values'", []
        allowed = {str(v) for v in values}
        bad = [n for n, v in cells if not is_empty(v) and str(v).strip() not in allowed]
        return ("fail" if bad else "pass"), f"{len(bad)} value(s) outside the set", bad
    if kind == "range":
        low, high = rule.get("min"), rule.get("max")
        if low is None and high is None:
            return "not run", "range needs min, max or both", []
        bad = []
        for number, value in cells:
            if is_empty(value):
                continue
            if isinstance(low if low is not None else high, str):
                text = str(value).strip()
                inside = (low is None or text >= low) and (high is None or text <= high)
            else:
                amount = as_number(value)
                inside = amount is not None and (low is None or amount >= low) and (high is None or amount <= high)
            if not inside:
                bad.append(number)
        return ("fail" if bad else "pass"), f"{len(bad)} value(s) outside the range or not comparable", bad
    if kind == "pattern":
        try:
            regex = re.compile(rule.get("regex") or "")
        except re.error as exc:
            return "not run", f"the regex does not compile: {exc}", []
        if not rule.get("regex"):
            return "not run", "pattern needs 'regex'", []
        bad = [n for n, v in cells if not is_empty(v) and not regex.fullmatch(str(v).strip())]
        return ("fail" if bad else "pass"), f"{len(bad)} value(s) do not match", bad
    try:
        ref_path, ref_table = resolve(base, rule.get("ref"))
        _, ref_columns, ref_rows, _ = load_table(ref_path, ref_table)
    except Blocked as exc:
        return "not run", f"reference not readable: {exc}", []
    ref_column = rule.get("ref_column")
    if ref_column not in ref_columns:
        return "not run", f"reference column {ref_column!r} not found", []
    position = ref_columns.index(ref_column)
    known = {str(r[position]).strip() for r in ref_rows if not is_empty(r[position])}
    if not known:
        return "not run", "the reference column holds no values", []
    bad = [n for n, v in cells if not is_empty(v) and str(v).strip() not in known]
    return ("fail" if bad else "pass"), f"{len(bad)} value(s) not found in {os.path.basename(ref_path)}.{ref_column}", bad


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("rules", help="the JSON rules file")
    parser.add_argument("--max-show", type=int, default=20, help="how many failing row numbers to print per rule (default 20)")
    parser.add_argument("--quarantine", help="write failing rows with the rule name to this NEW CSV file")
    args = parser.parse_args()

    try:
        with open(args.rules, encoding="utf-8") as handle:
            spec = json.load(handle)
    except OSError as exc:
        blocked(f"cannot read the rules file {args.rules}: {exc.strerror}")
    except ValueError as exc:
        blocked(f"the rules file is not valid JSON: {exc}")
    rules = spec.get("rules") if isinstance(spec, dict) else None
    if not isinstance(rules, list) or not rules or not all(isinstance(r, dict) for r in rules):
        blocked("the rules file needs a non-empty 'rules' list of objects")
    if args.quarantine and os.path.exists(args.quarantine):
        blocked(f"{args.quarantine} already exists; choose a new file name")
    base = os.path.dirname(os.path.abspath(args.rules))
    try:
        path, table = resolve(base, spec.get("dataset"))
        kind, columns, rows, notes = load_table(path, table)
    except Blocked as exc:
        blocked(str(exc))

    report = Report()
    print(f"DATA CHECK {path}" + (f" table {notes['table']}" if kind == "sqlite" else ""))
    print(f"  {len(rows)} rows, {len(columns)} columns, {len(rules)} rules; row numbers count data rows, the header is not counted")
    if notes["ragged"]:
        report.fail(f"{len(notes['ragged'])} row(s) have the wrong number of fields (rows {brief(notes['ragged'])}); rules ran on padded rows")
    if notes["bad_lines"]:
        report.fail(f"{len(notes['bad_lines'])} line(s) are not JSON objects and were left out: lines {brief(notes['bad_lines'])}")
    allows_empty = any(r.get("type") == "row_count" and r.get("min") == 0 for r in rules)
    if not rows and not allows_empty:
        report.fail("the dataset has zero rows; add a row_count rule with min 0 if an empty dataset is allowed")

    quarantined = []
    print("\nRULES")
    for position, rule in enumerate(rules, 1):
        label = rule.get("name") or f"{rule.get('type')} {rule.get('column') or ','.join(rule.get('columns') or []) or ''}".strip()
        soft = rule.get("severity") == "soft"
        if rule.get("severity") not in (None, "hard", "soft"):
            state, detail, bad = "not run", f"severity must be hard or soft, not {rule.get('severity')!r}", []
        else:
            state, detail, bad = run_rule(rule, columns, rows, base)
        shown = f"; rows {brief(bad, args.max_show)}" if bad else ""
        print(f"  {position}. [{state}] {label}: {detail}{shown}")
        line = f"rule {position} ({label}): {detail}{shown}"
        if state == "pass":
            report.ok(line)
        elif state == "not run":
            report.skip(line)
        elif soft:
            report.warn(line + " (soft rule)")
        else:
            report.fail(line)
        quarantined += [(number, label) for number in bad]

    if args.quarantine and quarantined:
        with open(args.quarantine, "x", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["row", "rule"] + columns)
            for number, label in sorted(quarantined):
                writer.writerow([number, label] + ["" if v is None else v for v in rows[number - 1]])
        print(f"\n{len(quarantined)} failing row entries written to {args.quarantine}")
    elif args.quarantine:
        print("\nno failing rows, so no quarantine file was written")
    hard = len(report.fails)
    return report.finish(f"{hard} hard failure(s)" if hard else None)


if __name__ == "__main__":
    sys.exit(main())

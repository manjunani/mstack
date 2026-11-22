#!/usr/bin/env python3
"""Apply named cleaning operations to a CSV file, write a NEW file, and log every single change.

  clean.py <input.csv> --plan plan.json --out NEW.csv [--log NEW.csv] [--removed NEW.csv]

The plan lists the operations, applied in order (see references/operations.md):

  { "operations": [
      { "op": "trim",            "columns": "*" },
      { "op": "case",            "columns": ["email"], "to": "lower" },
      { "op": "parse_date",      "columns": ["signup"], "formats": ["%d/%m/%Y", "%d %b %Y"] },
      { "op": "map",             "column": "country", "values": { "UK": "GB", "U.K.": "GB" } },
      { "op": "fill",            "column": "status", "value": "unknown" },
      { "op": "drop_duplicates" } ] }

What it will not do: it never writes over the input, never overwrites an existing output, and never picks a
fill value. "fill" needs the value stated in the plan; there is no mean, most-common or forward fill here.
A date is rewritten to ISO (YYYY-MM-DD) only when exactly one stated format reads it; a value that no format
reads, or that two formats read as different days, is left as it is and reported.

Outputs: the cleaned file; a change log with row, column, operation, before, after; and a file of removed rows
with the reason. After writing, the script replays the log on the input and compares the result with the
output file, so the log is proven to explain every difference.

Exit codes: 0 = written, and the log explains the output exactly (zero changes is a pass)
            1 = written, but some values could not be cleaned as asked, or the replay does not match
            2 = blocked: bad plan, unknown column, a fill with no value, existing output, input that is not a sound CSV
"""
import argparse
import csv
import datetime
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

OPS = ("trim", "case", "parse_date", "map", "fill", "drop_duplicates")
ISO = re.compile(r"\d{4}-\d{2}-\d{2}$")


def columns_of(op, columns):
    """The column positions an operation applies to; raises Blocked when a column is unknown."""
    names = op.get("columns", op.get("column"))
    if names in ("*", None) and op["op"] in ("trim", "drop_duplicates"):
        return list(range(len(columns)))
    if isinstance(names, str):
        names = [names]
    if not isinstance(names, list) or not names:
        raise Blocked(f"operation {op['op']} needs 'column' or 'columns'")
    missing = [n for n in names if n not in columns]
    if missing:
        raise Blocked(f"operation {op['op']} names column(s) that are not in the file: {', '.join(missing)}")
    return [columns.index(n) for n in names]


def check_plan(plan, columns):
    operations = plan.get("operations") if isinstance(plan, dict) else None
    if not isinstance(operations, list) or not operations:
        raise Blocked("the plan needs a non-empty 'operations' list")
    for op in operations:
        if not isinstance(op, dict) or op.get("op") not in OPS:
            raise Blocked(f"unknown operation {op.get('op') if isinstance(op, dict) else op!r}; known: {', '.join(OPS)}")
        columns_of(op, columns)
        if op["op"] == "case" and op.get("to") not in ("lower", "upper", "title"):
            raise Blocked("case needs 'to': lower, upper or title")
        if op["op"] == "parse_date" and not (isinstance(op.get("formats"), list) and op["formats"]):
            raise Blocked("parse_date needs 'formats': the list of date formats that occur, for example [\"%d/%m/%Y\"]. The script does not guess day and month order.")
        if op["op"] == "map" and not (isinstance(op.get("values"), dict) and op["values"]):
            raise Blocked("map needs 'values': an object of old value to new value")
        if op["op"] == "fill" and ("value" not in op or op["value"] is None or str(op["value"]) == ""):
            raise Blocked("fill needs a stated 'value'. This script never picks a fill value: ask the owner of the data what an empty cell means.")
    return operations


def read_date(text, formats):
    """Return the set of ISO dates the stated formats give for this text."""
    found = set()
    for fmt in formats:
        try:
            found.add(datetime.datetime.strptime(text.strip(), fmt).date().isoformat())
        except ValueError:
            continue
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", help="the CSV file to clean; it is only read")
    parser.add_argument("--plan", required=True, help="JSON file listing the operations")
    parser.add_argument("--out", required=True, help="NEW file for the cleaned data")
    parser.add_argument("--log", help="NEW file for the change log (default: <out>.changes.csv)")
    parser.add_argument("--removed", help="NEW file for removed rows (default: <out>.removed.csv)")
    args = parser.parse_args()

    log_path = args.log or args.out + ".changes.csv"
    removed_path = args.removed or args.out + ".removed.csv"
    for path in (args.out, log_path, removed_path):
        if os.path.exists(path):
            blocked(f"{path} already exists; this script writes only new files. Choose another name.")
    if len({os.path.abspath(p) for p in (args.input, args.out, log_path, removed_path)}) < 4:
        blocked("the input, output, log and removed-rows paths must be four different files")
    try:
        with open(args.plan, encoding="utf-8") as handle:
            plan = json.load(handle)
    except OSError as exc:
        blocked(f"cannot read the plan {args.plan}: {exc.strerror}")
    except ValueError as exc:
        blocked(f"the plan is not valid JSON: {exc}")
    try:
        kind, columns, rows, notes = load_table(args.input)
        if kind != "csv":
            raise Blocked(f"{args.input} is {kind}, and this script cleans CSV only; export it to CSV first")
        if notes["ragged"]:
            raise Blocked(f"{len(notes['ragged'])} row(s) have the wrong number of fields (rows {brief(notes['ragged'])}); fix the structure before cleaning values")
        if notes["renamed"]:
            raise Blocked(f"column names repeat in the header: {', '.join(sorted(set(notes['renamed'])))}")
        operations = check_plan(plan, columns)
    except Blocked as exc:
        blocked(str(exc))

    report = Report()
    work = [[number, list(row)] for number, row in enumerate(rows, 1)]
    log, removed = [], []

    def change(number, column, name, before, after):
        log.append([number, column, name, before, after])

    print(f"DATA CLEAN {args.input} -> {args.out}")
    print(f"  {len(rows)} rows, {len(columns)} columns, {len(operations)} operation(s)")
    print("\nOPERATIONS")
    for position, op in enumerate(operations, 1):
        name, index, before_count = op["op"], columns_of(op, columns), len(log)
        problems = []
        if name == "drop_duplicates":
            first, kept = {}, []
            for number, cells in work:
                key = tuple(cells[i] for i in index)
                if key in first:
                    removed.append([number, f"exact duplicate of row {first[key]}"] + cells)
                    change(number, "*", name, "present", f"removed, same as row {first[key]}")
                else:
                    first[key] = number
                    kept.append([number, cells])
            work = kept
        else:
            for number, cells in work:
                for i in index:
                    old = cells[i]
                    new = old
                    if name == "trim":
                        new = old.strip()
                    elif name == "case":
                        new = getattr(old, op["to"])()
                    elif name == "map":
                        new = str(op["values"][old]) if old in op["values"] else old
                    elif name == "fill":
                        new = str(op["value"]) if old.strip() == "" else old
                    elif name == "parse_date" and old.strip() and not ISO.match(old.strip()):
                        dates = read_date(old, op["formats"])
                        if len(dates) == 1:
                            new = dates.pop()
                        else:
                            problems.append((number, columns[i], "no stated format reads it" if not dates else "the stated formats read it as different days"))
                    if new != old:
                        cells[i] = new
                        change(number, columns[i], name, old, new)
        done = len(log) - before_count
        where = "all columns" if len(index) == len(columns) else ", ".join(columns[i] for i in index)
        print(f"  {position}. {name} on {where}: {done} change(s)" + (f", {len(problems)} value(s) left as they were" if problems else ""))
        if problems:
            sample = "; ".join(f"row {n} {c} ({why})" for n, c, why in problems[:8])
            report.fail(f"operation {position} ({name}) could not clean {len(problems)} value(s): {sample}" + (f" and {len(problems) - 8} more" if len(problems) > 8 else ""))
        else:
            report.ok(f"operation {position} ({name} on {where}) applied: {done} change(s)")

    with open(args.out, "x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        writer.writerows(cells for _, cells in work)
    with open(log_path, "x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["row", "column", "operation", "before", "after"])
        writer.writerows(log)
    with open(removed_path, "x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["row", "reason"] + columns)
        writer.writerows(removed)

    # Proof: replay the log on a fresh read of the input and compare with a fresh read of the output.
    _, _, fresh, _ = load_table(args.input)
    replay, gone, broken = {n: list(r) for n, r in enumerate(fresh, 1)}, set(), 0
    with open(log_path, encoding="utf-8", newline="") as handle:
        for entry in list(csv.reader(handle))[1:]:
            number, column, _, before, after = int(entry[0]), entry[1], entry[2], entry[3], entry[4]
            if column == "*":
                gone.add(number)
            elif replay[number][columns.index(column)] != before:
                broken += 1
            else:
                replay[number][columns.index(column)] = after
    expected = [cells for number, cells in replay.items() if number not in gone]
    try:
        _, out_columns, written, _ = load_table(args.out)
    except Blocked:
        out_columns, written = columns, []
    if broken or out_columns != columns or written != expected:
        report.fail("replaying the change log on the input does not give the output file; do not use the output")
    else:
        report.ok(f"replaying the {len(log)} log line(s) on the input gives the output file exactly")
    if len(rows) == len(work) + len(removed):
        report.ok(f"row count holds: {len(rows)} in = {len(work)} out + {len(removed)} removed")
    else:
        report.fail(f"row count does not hold: {len(rows)} in, {len(work)} out, {len(removed)} removed")
    print(f"\nWRITTEN  cleaned: {args.out} ({len(work)} rows)   log: {log_path} ({len(log)} lines)   removed rows: {removed_path} ({len(removed)})")
    print(f"  the input {args.input} was not changed; the output is comma-separated UTF-8")
    if not log:
        print("  nothing needed changing: the output holds the same rows as the input")
    return report.finish()


if __name__ == "__main__":
    sys.exit(main())

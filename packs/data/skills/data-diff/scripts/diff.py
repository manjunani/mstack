#!/usr/bin/env python3
"""Compare two versions of a dataset by key and say exactly what changed. Read-only.

  diff.py <old> <new> --key id                     CSV, JSON-lines or SQLite on either side
  diff.py old.sqlite new.sqlite --key order_id,line --old-table orders --new-table orders
  diff.py before.csv after.csv --key id --changes-ok --json NEW_FILE

Rows are matched by the key, columns by name, so reordered rows and reordered columns are not differences.
Reports: columns added and removed; rows added, removed, changed and unchanged; for changed rows the count per
column and a sample of before and after values. The totals are checked: removed + changed + unchanged equals
the old row count, and added + changed + unchanged equals the new one.

Without --key the script stops and lists the columns that are unique in both files.
--loose compares numbers by value (1 equals 1.0) and ignores spaces around text.
--ignore a,b leaves those columns out of the comparison.

The report keeps three lists apart: findings, checked and fine, could not check.
Exit codes: 0 = no difference (or differences with --changes-ok)
            1 = the two versions differ, or one of them is structurally broken
            2 = blocked: no key, a key that is missing or not unique, an unreadable file
"""
import argparse
import collections
import csv
import io
import json
import os
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


def norm(value, loose):
    if value is None:
        return ""
    if loose:
        number = as_number(value)
        return repr(number) if number is not None else str(value).strip()
    return str(value)


def key_text(value):
    """Key values as text, so that 1 in SQLite and "1" in a CSV are the same key and "007" stays itself."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def keyed(label, columns, rows, key):
    """Return {key tuple: row number}; stop when the key is empty or repeated."""
    index = [columns.index(k) for k in key]
    seen, repeated, empty = {}, [], []
    for number, row in enumerate(rows, 1):
        value = tuple(key_text(row[i]) for i in index)
        if all(part == "" for part in value):
            empty.append(number)
        elif value in seen:
            repeated.append(number)
        else:
            seen[value] = number
    if empty or repeated:
        parts = []
        if repeated:
            parts.append(f"{len(repeated)} row(s) repeat a key (rows {brief(repeated, 8)})")
        if empty:
            parts.append(f"{len(empty)} row(s) have an empty key (rows {brief(empty, 8)})")
        raise Blocked(f"the key {','.join(key)} does not identify rows in the {label} file: " + "; ".join(parts) + ". Choose a key that is unique, or add a column to it.")
    return seen


def unique_columns(columns, rows):
    out = []
    for i, name in enumerate(columns):
        values = [key_text(row[i]) for row in rows]
        if rows and all(values) and len(set(values)) == len(values):
            out.append(name)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("old", help="the earlier version")
    parser.add_argument("new", help="the later version")
    parser.add_argument("--key", help="column, or columns joined by commas, that identify a row")
    parser.add_argument("--old-table", help="table name when the old file is SQLite with more than one table")
    parser.add_argument("--new-table", help="table name when the new file is SQLite with more than one table")
    parser.add_argument("--ignore", default="", help="columns to leave out of the comparison, joined by commas")
    parser.add_argument("--loose", action="store_true", help="compare numbers by value and ignore spaces around text")
    parser.add_argument("--max-show", type=int, default=10, help="how many changed values to print (default 10; 0 prints none)")
    parser.add_argument("--changes-ok", action="store_true", help="differences are expected: list them, and exit 0")
    parser.add_argument("--json", dest="json_out", help="write the full diff to this NEW file")
    args = parser.parse_args()

    if args.json_out and os.path.exists(args.json_out):
        blocked(f"{args.json_out} already exists; choose a new file name")
    try:
        _, old_columns, old_rows, old_notes = load_table(args.old, args.old_table)
        _, new_columns, new_rows, new_notes = load_table(args.new, args.new_table)
    except Blocked as exc:
        blocked(str(exc))
    shared = [c for c in old_columns if c in new_columns]
    if not args.key:
        both = [c for c in unique_columns(old_columns, old_rows) if c in unique_columns(new_columns, new_rows)]
        blocked("no key given. Columns that are unique and filled in both files: " + (", ".join(both) or "none; a key of several columns is needed")
                + ". Ask the owner of the data which one identifies a row, then pass --key.")
    key = [k.strip() for k in args.key.split(",") if k.strip()]
    absent = [k for k in key if k not in shared]
    if absent:
        blocked(f"key column(s) not in both files: {', '.join(absent)}. Shared columns: {', '.join(shared) or 'none'}")
    try:
        old_keys = keyed("old", old_columns, old_rows, key)
        new_keys = keyed("new", new_columns, new_rows, key)
    except Blocked as exc:
        blocked(str(exc))

    report = Report()
    differ = report.warn if args.changes_ok else report.fail
    print(f"DATA DIFF {args.old} -> {args.new}, key {','.join(key)}")
    print(f"  old: {len(old_rows)} rows, {len(old_columns)} columns; new: {len(new_rows)} rows, {len(new_columns)} columns")
    for label, notes in (("old", old_notes), ("new", new_notes)):
        if notes["ragged"]:
            report.fail(f"the {label} file has {len(notes['ragged'])} row(s) with the wrong number of fields: rows {brief(notes['ragged'])}")
        if notes["bad_lines"]:
            report.fail(f"the {label} file has {len(notes['bad_lines'])} line(s) that are not JSON objects: lines {brief(notes['bad_lines'])}")

    added_columns = [c for c in new_columns if c not in old_columns]
    removed_columns = [c for c in old_columns if c not in new_columns]
    if added_columns:
        differ(f"column(s) added: {', '.join(added_columns)}")
    if removed_columns:
        differ(f"column(s) removed: {', '.join(removed_columns)}")
    if not added_columns and not removed_columns:
        report.ok("same set of columns" + ("" if old_columns == new_columns else " (the order differs; columns were matched by name)"))
    ignored = {c.strip() for c in args.ignore.split(",") if c.strip()}
    unknown = sorted(ignored - set(shared))
    if unknown:
        report.skip(f"--ignore names column(s) that are not in both files: {', '.join(unknown)}")
    compared = [c for c in shared if c not in ignored and c not in key]

    added = [k for k in new_keys if k not in old_keys]
    removed = [k for k in old_keys if k not in new_keys]
    per_column, changes, changed, unchanged = collections.Counter(), [], 0, 0
    for k, old_number in old_keys.items():
        if k not in new_keys:
            continue
        old_row, new_row = old_rows[old_number - 1], new_rows[new_keys[k] - 1]
        hit = False
        for column in compared:
            before, after = old_row[old_columns.index(column)], new_row[new_columns.index(column)]
            if norm(before, args.loose) != norm(after, args.loose):
                hit = True
                per_column[column] += 1
                changes.append({"key": list(k), "column": column, "before": before, "after": after})
        changed += hit
        unchanged += not hit

    print(f"\nROWS  added {len(added)}, removed {len(removed)}, changed {changed}, unchanged {unchanged}")
    old_total, new_total = len(removed) + changed + unchanged, len(added) + changed + unchanged
    print(f"  totals: {len(removed)} + {changed} + {unchanged} = {old_total} (old has {len(old_rows)}); "
          f"{len(added)} + {changed} + {unchanged} = {new_total} (new has {len(new_rows)})")
    if old_total != len(old_rows) or new_total != len(new_rows):
        report.fail("the totals do not add up to the row counts; do not trust this diff")
    else:
        report.ok("the totals add up to both row counts")
    show = lambda keys: ", ".join("/".join(k) for k in keys[:max(args.max_show, 0)]) + (f" and {len(keys) - args.max_show} more" if len(keys) > args.max_show else "")
    if added:
        differ(f"{len(added)} row(s) added" + (f": keys {show(added)}" if args.max_show > 0 else ""))
    if removed:
        differ(f"{len(removed)} row(s) removed" + (f": keys {show(removed)}" if args.max_show > 0 else ""))
    if changed:
        differ(f"{changed} row(s) changed; per column: " + ", ".join(f"{c} {n}" for c, n in per_column.most_common()))
        if args.max_show > 0:
            print("\nCHANGED VALUES (key: column: before -> after)")
            for change in changes[:args.max_show]:
                print(f"  {'/'.join(change['key'])}: {change['column']}: {change['before']!r} -> {change['after']!r}")
            if len(changes) > args.max_show:
                print(f"  and {len(changes) - args.max_show} more (use --json for all)")
    if not (added or removed or changed):
        report.ok(f"all {unchanged} rows match on {len(compared)} compared column(s)")
    common = [k for k in old_keys if k in new_keys]
    if common != [k for k in new_keys if k in old_keys]:
        report.ok("row order differs between the files; rows were matched by key, so order is not a difference")
    if ignored & set(shared):
        report.skip(f"column(s) left out by --ignore: {', '.join(sorted(ignored & set(shared)))}")

    if args.json_out:
        payload = {"old": args.old, "new": args.new, "key": key, "old_rows": len(old_rows), "new_rows": len(new_rows),
                   "columns_added": added_columns, "columns_removed": removed_columns, "rows_added": [list(k) for k in added],
                   "rows_removed": [list(k) for k in removed], "rows_changed": changed, "rows_unchanged": unchanged,
                   "changes_per_column": dict(per_column), "changes": changes, **report.as_dict()}
        with open(args.json_out, "x", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, default=str)
        print(f"\nfull diff written to {args.json_out}")
    summary = f"the versions differ: {len(added)} added, {len(removed)} removed, {changed} changed" + (
        f", {len(added_columns)} column(s) added, {len(removed_columns)} removed" if added_columns or removed_columns else "")
    return report.finish(summary if report.fails else None)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Tie every number in a report to the query or aggregate that produced it, and run each one again.

  trace.py <report.md> <sources.json>

The sources file maps each number, written as it appears in the report, to where it came from:

  { "ignore": ["2026"],
    "numbers": [
      { "value": "1,204", "label": "orders in October", "data": "shop.sqlite",
        "sql": "SELECT count(*) FROM orders WHERE month = '2026-10'" },
      { "value": "38.5",  "label": "mean basket", "data": "orders.csv",
        "aggregate": "mean", "column": "amount", "where": { "status": "paid" } },
      { "value": "12%",   "label": "refund share", "data": "orders.csv",
        "aggregate": "share", "where": { "status": "refunded" } },
      { "value": "4.2",   "label": "survey score", "note": "from the vendor's PDF, page 3" } ] }

Paths are relative to the sources file. "sql" runs on a SQLite file through a read-only guard (one SELECT or
WITH statement; the first cell of the first row is the number). "aggregate" is count, sum, mean, median, min,
max, distinct or share, over a CSV, JSON-lines or SQLite table ("table" names it), with optional equality
filters in "where". "scale" multiplies the re-run value before it is compared (share is already in percent).
An entry with neither has a source that cannot be re-run here.

Every number in the report ends in one of: matches, does not match, has no source, cannot be re-run.
Exit codes: 0 = every number has a source and every re-run matches
            1 = a number does not match, or has no source
            2 = not verified or blocked: a source could not be re-run, or a file is unusable
Nothing is changed. See references/sources.md for which numbers are read out of the report.
"""
import argparse
import csv
import io
import json
import os
import re
import sqlite3
import statistics
import sys
import time
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

# --- shared block: read-only SQL guard (the same text is in sql-run, number-trace and query-review) ---
WRITE_WORDS = {"insert", "update", "delete", "drop", "alter", "create", "truncate", "grant", "revoke", "merge",
               "attach", "detach", "pragma", "vacuum", "reindex", "into", "replace"}


def scan_sql(sql, brackets=True):
    """Split SQL at semicolons that are outside strings, quoted names and comments.
    Return a list of (statement, skeleton). Comments are removed from both. In the skeleton the inside of
    every string and quoted name is blanked, so a keyword search cannot be fooled by text in quotes.
    Raise ValueError when a quote is never closed."""
    quotes = "'\"`[" if brackets else "'\"`"
    pairs, text, skel, i, n = [], [], [], 0, len(sql)

    def flush():
        statement, skeleton = "".join(text).strip(), "".join(skel).strip()
        if skeleton:
            pairs.append((statement, skeleton))
        text.clear()
        skel.clear()

    while i < n:
        ch, two = sql[i], sql[i:i + 2]
        if two == "--" or two == "/*":
            end = sql.find("\n", i) if two == "--" else sql.find("*/", i + 2)
            i = n if end == -1 else end + (0 if two == "--" else 2)
            text.append(" ")
            skel.append(" ")
        elif ch in quotes:
            close, j = ("]" if ch == "[" else ch), i + 1
            while j < n and not (sql[j] == close and (close == "]" or sql[j + 1:j + 2] != close)):
                j += 2 if sql[j] == close else 1
            if j >= n:
                raise ValueError(f"a {ch} quote is never closed")
            text.append(sql[i:j + 1])
            skel.append(ch + " " * (j - i - 1) + close)
            i = j + 1
        elif ch == "$" and re.match(r"\$[A-Za-z_]*\$", sql[i:]):
            tag = re.match(r"\$[A-Za-z_]*\$", sql[i:]).group(0)
            end = sql.find(tag, i + len(tag))
            if end == -1:
                raise ValueError(f"a {tag} quote is never closed")
            text.append(sql[i:end + len(tag)])
            skel.append("'" + " " * (end + len(tag) - i - 2) + "'")
            i = end + len(tag)
        elif ch == ";":
            flush()
            i += 1
        else:
            text.append(ch)
            skel.append(ch)
            i += 1
    flush()
    return pairs


def read_only_problems(sql, brackets=True):
    """Return (statement, skeleton, problems). An empty problem list means exactly one statement that starts
    with SELECT or WITH and holds no write keyword outside quotes. This is a text check: it can be fooled by a
    function with side effects, so the database's own read-only mode or role is the real guard."""
    try:
        pairs = scan_sql(sql, brackets)
    except ValueError as exc:
        return "", "", [str(exc)]
    if not pairs:
        return "", "", ["no SQL statement found"]
    statement, skeleton = pairs[0]
    problems = []
    if len(pairs) > 1:
        problems.append(f"{len(pairs)} statements found; exactly one is allowed")
    words = re.findall(r"[a-z_][a-z_0-9]*", skeleton.lower())
    if not words or words[0] not in ("select", "with"):
        problems.append(f"the statement starts with {(words[0] if words else 'nothing').upper()}; only SELECT or WITH is allowed")
    lowered = skeleton.lower()
    for match in re.finditer(r"[a-z_][a-z_0-9]*", lowered):
        word = match.group(0)
        if word in WRITE_WORDS and not (word == "replace" and lowered[match.end():].lstrip().startswith("(")):
            text = f"it contains the keyword {word.upper()} (put a column of that name in double quotes)"
            if text not in problems:
                problems.append(text)
    return statement, skeleton, problems


def top_level_words(skeleton):
    """Lower-case words of the skeleton that are not inside any parentheses."""
    depth, out, word = 0, [], []
    for ch in skeleton.lower() + " ":
        if ch.isalnum() or ch == "_":
            if depth == 0:
                word.append(ch)
            continue
        if word:
            out.append("".join(word))
            word = []
        depth += (ch == "(") - (ch == ")")
    return out


def has_row_limit(skeleton):
    words = top_level_words(skeleton)
    return "limit" in words or "top" in words[1:2] or ("fetch" in words and ("first" in words or "next" in words))


def open_read_only(path):
    """Open a SQLite file so that it cannot be changed: read-only URI, query_only, and an authorizer that
    allows nothing but reading."""
    uri = "file:" + urllib.parse.quote(os.path.abspath(path)) + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.execute("PRAGMA query_only = ON")
    allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, getattr(sqlite3, "SQLITE_RECURSIVE", 33)}
    conn.set_authorizer(lambda action, *rest: sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY)
    return conn


def set_time_limit(conn, seconds):
    """Interrupt any statement on this connection that is still running after the given time."""
    deadline = time.monotonic() + seconds
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 2000)


def is_sqlite_file(path):
    try:
        with open(path, "rb") as handle:
            return handle.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False
# --- end of shared block ---

NUMBER = re.compile(r"(?<![\w.,/:-])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?(?![\w/-]|[.,:]\d)")
AGGREGATES = ("count", "sum", "mean", "median", "min", "max", "distinct", "share")
SQL_SECONDS = 10


def parse_number(token):
    """Return (value, is_percent, decimals) for a number as written, or None."""
    text = str(token).strip()
    percent = text.endswith("%")
    text = text.rstrip("%").replace(",", "").lstrip("+")
    try:
        value = float(text)
    except ValueError:
        return None
    return value, percent, (len(text.split(".")[1]) if "." in text else 0)


def numbers_in(report_text):
    """Return {(value, is_percent): {"written": first spelling, "lines": [...], "decimals": least shown}}."""
    found, in_code = {}, False
    for line_number, line in enumerate(report_text.splitlines(), 1):
        if line.lstrip().startswith(("```", "~~~")):
            in_code = not in_code
            continue
        if in_code:
            continue
        line = re.sub(r"`[^`]*`", " ", line)
        line = re.sub(r"https?://\S+", " ", line)
        line = re.sub(r"^\s*(#+\s*)?\d+(\.\d+)*[.)]\s", " ", line)
        for match in NUMBER.finditer(line):
            value, percent, decimals = parse_number(match.group(0))
            entry = found.setdefault((value, percent), {"written": match.group(0), "lines": [], "decimals": decimals})
            entry["lines"].append(line_number)
            entry["decimals"] = min(entry["decimals"], decimals)
    return found


def rerun(entry, base):
    """Return (value, how) or raise Blocked with the reason the source cannot be re-run."""
    data = entry.get("data")
    if not data or not (entry.get("sql") or entry.get("aggregate")):
        raise Blocked("the entry names no query or aggregate to run" + (f" (note: {entry['note']})" if entry.get("note") else ""))
    path = data if os.path.isabs(data) else os.path.join(base, data)
    if not os.path.isfile(path):
        raise Blocked(f"data file not found: {data}")
    if entry.get("sql"):
        if not is_sqlite_file(path):
            raise Blocked(f"'sql' needs a SQLite file, and {data} is not one")
        statement, _, problems = read_only_problems(entry["sql"])
        if problems:
            raise Blocked("the query was refused: " + "; ".join(problems))
        try:
            conn = open_read_only(path)
            set_time_limit(conn, SQL_SECONDS)
            row = conn.execute(statement).fetchone()
            conn.close()
        except sqlite3.Error as exc:
            raise Blocked(f"the query did not run: {exc}")
        value = as_number(row[0]) if row else None
        if value is None:
            raise Blocked("the query's first cell is not a number" if row else "the query returned no rows")
        return value, f"sql on {data}"
    kind = entry["aggregate"]
    if kind not in AGGREGATES:
        raise Blocked(f"unknown aggregate {kind!r}; known: {', '.join(AGGREGATES)}")
    _, columns, rows, notes = load_table(path, entry.get("table"))
    where = entry.get("where") or {}
    absent = [name for name in list(where) + ([entry["column"]] if entry.get("column") else []) if name not in columns]
    if absent:
        raise Blocked(f"column(s) not in {data}: {', '.join(absent)}")
    chosen = [row for row in rows if all(str(row[columns.index(k)]).strip() == str(v) for k, v in where.items())]
    how = f"{kind}" + (f" of {entry['column']}" if entry.get("column") else "") + f" on {data}" + (f" where {where}" if where else "")
    if kind == "share":
        if not rows:
            raise Blocked("the dataset has no rows")
        return 100.0 * len(chosen) / len(rows), how + f" ({len(chosen)} of {len(rows)} rows)"
    if kind == "count" and not entry.get("column"):
        return float(len(chosen)), how
    if not entry.get("column"):
        raise Blocked(f"{kind} needs a column")
    cells = [row[columns.index(entry["column"])] for row in chosen if not is_empty(row[columns.index(entry["column"])])]
    if kind == "count":
        return float(len(cells)), how
    if kind == "distinct":
        return float(len({str(c).strip() for c in cells})), how
    numbers = [as_number(c) for c in cells]
    if not numbers or any(n is None for n in numbers):
        raise Blocked(f"{sum(1 for n in numbers if n is None)} value(s) of {entry['column']} are not numbers" if numbers else "no rows match the filter")
    result = {"sum": sum, "mean": statistics.fmean, "median": statistics.median, "min": min, "max": max}[kind](numbers)
    return float(result), how + f" ({len(numbers)} values)"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("report", help="the report, as text or Markdown")
    parser.add_argument("sources", help="the JSON sources file")
    args = parser.parse_args()

    try:
        report_text = open(args.report, encoding="utf-8").read()
    except (OSError, UnicodeDecodeError) as exc:
        blocked(f"cannot read the report {args.report}: {exc}")
    try:
        spec = json.load(open(args.sources, encoding="utf-8"))
    except OSError as exc:
        blocked(f"cannot read the sources file {args.sources}: {exc.strerror}")
    except ValueError as exc:
        blocked(f"the sources file is not valid JSON: {exc}")
    entries = spec.get("numbers") if isinstance(spec, dict) else None
    if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
        blocked("the sources file needs a 'numbers' list of objects")
    base = os.path.dirname(os.path.abspath(args.sources))

    found = numbers_in(report_text)
    ignored = {parse_number(token)[:2] for token in spec.get("ignore", []) if parse_number(token)}
    report = Report()
    print(f"NUMBER TRACE {args.report} against {args.sources}")
    print(f"  {len(found)} distinct numbers read from the report, {len(entries)} source entries, {len(ignored & set(found))} ignored by the sources file")
    if not found:
        report.fail("no numbers were read from the report; check that this is the right file")

    by_key = {}
    for position, entry in enumerate(entries, 1):
        parsed = parse_number(entry.get("value", ""))
        label = entry.get("label") or f"entry {position}"
        if parsed is None:
            report.skip(f"source entry '{label}': its value {entry.get('value')!r} is not a number")
            continue
        key = parsed[:2]
        if key in by_key:
            report.warn(f"source entry '{label}' repeats the value {entry['value']}; the first entry for it is used")
            continue
        by_key[key] = (entry, label)
        if key not in found:
            report.warn(f"source entry '{label}' ({entry['value']}) does not appear in the report; the sources file may be stale")

    for key in sorted(found, key=lambda k: found[k]["lines"][0]):
        seen = found[key]
        place = f"{seen['written']} (line {brief(seen['lines'], 4)})"
        if key in ignored:
            continue
        if key not in by_key:
            report.fail(f"{place}: no source")
            continue
        entry, label = by_key[key]
        try:
            value, how = rerun(entry, base)
        except Blocked as exc:
            report.skip(f"{place} '{label}': has a source but was not re-run: {exc}")
            continue
        value *= float(entry.get("scale", 1))
        if abs(value - key[0]) <= 0.5 * 10 ** -seen["decimals"] + 1e-9:
            report.ok(f"{place} '{label}': re-run gives {value:.6g} ({how})")
        else:
            report.fail(f"{place} '{label}': does not match, re-run gives {value:.6g} ({how})")
    if ignored & set(found):
        print("  ignored as not data: " + ", ".join(found[k]["written"] for k in sorted(ignored & set(found))))
    unmatched = sum(1 for t in report.fails if "does not match" in t)
    unsourced = sum(1 for t in report.fails if t.endswith("no source"))
    return report.finish(f"{unmatched} number(s) do not match and {unsourced} have no source" if report.fails else None)


if __name__ == "__main__":
    sys.exit(main())

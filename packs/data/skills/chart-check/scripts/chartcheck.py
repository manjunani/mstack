#!/usr/bin/env python3
"""Check a chart described as a JSON spec: is it correct against its data, and can it be read? Read-only.

  chartcheck.py <spec.json>

The spec states what the chart shows (see references/spec.md for every field):

  { "type": "bar", "title": "Revenue by month",
    "x": { "label": "Month", "categories": ["Jan", "Feb", "Mar"], "ordered": true },
    "y": { "label": "Revenue", "unit": "EUR thousand", "min": 0, "max": 60 },
    "series": [ { "name": "2026", "values": [41, 38, 52] } ],
    "source": { "file": "revenue.csv", "category_column": "month", "series": { "2026": "revenue_k" } } }

Checks: a bar or area axis that does not start at zero; data outside the stated axis range; missing axis
labels, units or title; more series than the limit; a pie chart with many slices, negative values or several
series; two value axes; series whose length differs from the categories; repeated categories; ordered
categories (dates, months, weekdays, quarters, numbers) that are out of order; unordered bars that are not
sorted by value; and every plotted value compared with the source file named in the spec.

The report keeps three lists apart: findings, checked and fine, could not check.
Exit codes: 0 = no blocking finding (warnings may be listed) and the values matched the source
            1 = a blocking finding: wrong values, a truncated bar axis, clipped data, missing labels, a broken spec
            2 = not verified or blocked: no source to compare with, an axis range not stated, or an unusable spec file
The script reads the spec and the source. It does not see the rendered image; colour, overlap and font size are not checked.
"""
import argparse
import csv
import io
import json
import os
import pathlib
import re
import sqlite3
import statistics
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
FALLBACK = {"max_series": 6, "max_pie_slices": 5, "min_bars_to_sort": 4}
TYPES = ("bar", "line", "area", "pie", "scatter")
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def load_limits():
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


def order_keys(categories):
    """Sortable keys when the categories have a natural order this script knows, else None."""
    texts = [str(c).strip().lower() for c in categories]
    if all(as_number(c) is not None for c in categories):
        return [as_number(c) for c in categories]
    if all(re.fullmatch(r"\d{4}(-\d{2}){0,2}", t) for t in texts):
        return texts
    if all(re.fullmatch(r"(\d{4}\s*)?q[1-4](\s*\d{4})?", t) for t in texts):
        return [("".join(re.findall(r"\d{4}", t)), re.search(r"q([1-4])", t).group(1)) for t in texts]
    for names in (MONTHS, DAYS):
        if all(t[:3] in names for t in texts):
            return [names.index(t[:3]) for t in texts]
    return None


def decimals_of(value):
    text = repr(value) if not isinstance(value, str) else value
    return len(text.split(".")[1]) if "." in text and "e" not in text.lower() else 0


def check_source(spec, base, categories, series, report):
    source = spec.get("source")
    if not isinstance(source, dict) or not source.get("file"):
        report.skip("the plotted values were not compared with any data: the spec names no source file")
        return
    path = source["file"] if os.path.isabs(source["file"]) else os.path.join(base, source["file"])
    try:
        _, columns, rows, _ = load_table(path, source.get("table"))
    except Blocked as exc:
        report.skip(f"the plotted values were not compared with the source: {exc}")
        return
    category_column, mapping = source.get("category_column"), source.get("series") or {}
    how = source.get("aggregate", "none")
    scale = as_number(source.get("scale", 1)) or 1.0
    if category_column not in columns or how not in ("none", "sum", "mean", "count"):
        report.skip(f"the plotted values were not compared with the source: category_column {category_column!r} not found, or aggregate {how!r} unknown")
        return
    ci = columns.index(category_column)
    for item in series:
        name = item.get("name", "")
        column = mapping.get(name, name)
        if how != "count" and column not in columns:
            report.skip(f"series '{name}': source column {column!r} not found in {source['file']}")
            continue
        wrong, checked = [], 0
        for category, shown in zip(categories, item.get("values") or []):
            cells = [row for row in rows if str(row[ci]).strip() == str(category).strip()]
            if not cells:
                wrong.append(f"{category}: not in the source")
                continue
            if how == "count":
                real = float(len(cells))
            else:
                numbers = [as_number(row[columns.index(column)]) for row in cells]
                if any(n is None for n in numbers):
                    wrong.append(f"{category}: the source value is not a number")
                    continue
                if how == "none" and len(numbers) > 1:
                    wrong.append(f"{category}: {len(numbers)} source rows and no aggregate stated")
                    continue
                real = numbers[0] if how == "none" else (sum(numbers) if how == "sum" else statistics.fmean(numbers))
            real *= scale
            plotted = as_number(shown)
            checked += 1
            if plotted is None or abs(plotted - real) > 0.5 * 10 ** -decimals_of(shown) + 1e-9:
                wrong.append(f"{category}: chart shows {shown}, source gives {real:.6g}")
        label = f"series '{name}' against {source['file']}" + (f" ({how} of {column})" if how != "none" else f" ({column})")
        if wrong:
            report.fail(f"{label}: {len(wrong)} value(s) do not match: " + "; ".join(wrong[:6]) + (f" and {len(wrong) - 6} more" if len(wrong) > 6 else ""))
        else:
            report.ok(f"{label}: all {checked} values match")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("spec", help="the chart spec, a JSON file")
    args = parser.parse_args()
    try:
        with open(args.spec, encoding="utf-8") as handle:
            spec = json.load(handle)
    except OSError as exc:
        blocked(f"cannot read {args.spec}: {exc.strerror}")
    except ValueError as exc:
        blocked(f"the spec is not valid JSON: {exc}")
    if not isinstance(spec, dict) or spec.get("type") not in TYPES:
        blocked(f"the spec needs \"type\": one of {', '.join(TYPES)}")
    series = spec.get("series")
    if not isinstance(series, list) or not series or not all(isinstance(s, dict) and isinstance(s.get("values"), list) for s in series):
        blocked("the spec needs \"series\": a list of objects, each with \"values\"")
    limits, limit_lines = load_limits()
    kind = spec["type"]
    x = spec.get("x") if isinstance(spec.get("x"), dict) else {}
    y = spec.get("y") if isinstance(spec.get("y"), dict) else {}
    y2 = spec.get("y2") if isinstance(spec.get("y2"), dict) else None
    categories = x.get("categories") or []
    report = Report()
    print(f"CHART CHECK {args.spec}: {kind}, {len(series)} series, {len(categories)} categories")
    for line in limit_lines:
        print(f"  note: {line}")

    if not str(spec.get("title") or "").strip():
        report.warn("no title: the reader cannot tell what the chart claims")
    axes = [("y", y)] + ([("y2", y2)] if y2 else []) if kind != "pie" else []
    if kind != "pie":
        missing = [name for name, axis in [("x", x)] + axes if not str(axis.get("label") or "").strip()]
        if missing:
            report.fail(f"axis label missing on: {', '.join(missing)}")
        else:
            report.ok("every axis has a label")
        no_unit = [name for name, axis in axes if not str(axis.get("unit") or "").strip()]
        if no_unit:
            report.warn(f"no unit on the value axis: {', '.join(no_unit)} (write \"count\" or \"none\" when there is none)")
        else:
            report.ok("the value axis states its unit")

    lengths = sorted({len(s["values"]) for s in series})
    if kind != "scatter" and (len(lengths) > 1 or (categories and lengths[0] != len(categories))):
        report.fail(f"series lengths {lengths} do not all equal the {len(categories)} categories")
    elif kind != "scatter":
        report.ok("every series has one value per category")
    repeats = sorted({str(c) for c in categories if [str(k) for k in categories].count(str(c)) > 1})
    if repeats:
        report.fail(f"categories repeat: {', '.join(repeats)}")
    gaps = sum(1 for s in series for v in s["values"] if as_number(v) is None)
    if gaps:
        report.warn(f"{gaps} plotted value(s) are missing or not numbers; say in the chart how gaps are drawn")
    values = {name: [as_number(v) for s in series if s.get("axis", "y") == name for v in s["values"] if as_number(v) is not None] for name in ("y", "y2")}

    if len(series) > limits["max_series"] and kind != "pie":
        report.warn(f"{len(series)} series on one chart (limit {limits['max_series']}): the reader cannot tell them apart; group the small ones or split the chart")
    elif kind != "pie":
        report.ok(f"{len(series)} series, within the limit of {limits['max_series']}")
    if y2 or any(s.get("axis") == "y2" for s in series):
        report.warn("two value axes: where the lines cross and how steep they look depends only on the two scales chosen; two charts side by side are safer")

    if kind == "pie":
        if len(series) > 1:
            report.fail("a pie chart can show one series; this spec has several")
        slices = [as_number(v) for v in series[0]["values"]]
        if any(v is not None and v < 0 for v in slices):
            report.fail("a pie chart cannot show negative values")
        if len(slices) > limits["max_pie_slices"]:
            report.warn(f"{len(slices)} slices (limit {limits['max_pie_slices']}): small angles cannot be compared by eye; a sorted bar chart reads better")
        else:
            report.ok(f"{len(slices)} slices, within the limit of {limits['max_pie_slices']}")
    for name, axis in axes:
        low, high, points = as_number(axis.get("min")), as_number(axis.get("max")), values[name]
        if not points:
            continue
        truncated = False
        if kind in ("bar", "area") and axis.get("scale") != "log":
            if low is None:
                report.skip(f"{name} axis: no \"min\" in the spec, so a truncated {kind} axis cannot be ruled out; state the value the renderer uses")
            elif (low > 0 and min(points) >= 0) or (high is not None and high < 0 and max(points) <= 0):
                truncated = True
                biggest, smallest = max(points), min(points)
                seen = (f"; the tallest bar looks {(biggest - low) / (smallest - low):.1f} times the shortest, the real ratio is {biggest / smallest:.1f}"
                        if low > 0 and smallest > low else "")
                report.fail(f"{name} axis of a {kind} chart starts at {low if low > 0 else high:g}, not 0: bar lengths no longer match the values{seen}")
            else:
                report.ok(f"{name} axis of the {kind} chart includes zero")
        elif low is not None and low != 0 and kind == "line":
            report.ok(f"{name} axis starts at {low:g}; allowed for a line chart, but say so near the chart when differences look large")
        outside = [p for p in points if (low is not None and p < low) or (high is not None and p > high)]
        if outside:
            report.fail(f"{len(outside)} value(s) fall outside the {name} axis range {low if low is not None else '-'} to {high if high is not None else '-'} and are cut off")
        elif (low is not None or high is not None) and not truncated:
            report.ok(f"all values fit inside the stated {name} axis range")

    if categories and kind != "scatter":
        keys = order_keys(categories)
        ordered = x.get("ordered")
        if ordered or (ordered is None and keys is not None):
            if keys is None:
                report.skip("the categories are marked as ordered, but they are not numbers, dates, months, weekdays or quarters, so their order was not judged")
            elif keys != sorted(keys):
                report.fail("the categories have a natural order and are not in it: " + ", ".join(str(c) for c in categories[:8]))
            else:
                report.ok("ordered categories are in their natural order")
        elif kind in ("bar", "pie") and len(series) == 1 and len(categories) >= limits["min_bars_to_sort"]:
            shown = [as_number(v) for v in series[0]["values"]]
            if None not in shown and shown != sorted(shown) and shown != sorted(shown, reverse=True):
                report.warn("the categories have no order of their own and are not sorted by value; sorted bars are compared faster")
            elif None not in shown:
                report.ok("categories without an order of their own are sorted by value")
    check_source(spec, os.path.dirname(os.path.abspath(args.spec)), categories, series, report)
    return report.finish()


if __name__ == "__main__":
    sys.exit(main())

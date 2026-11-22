#!/usr/bin/env python3
"""Compare two groups of numbers from the raw rows, with each assumption checked and stated. Read-only.

  compare.py <file> --value amount --group variant --unit user_id
  compare.py <file> --value secs --group arm --a control --b new --claim b-higher
  compare.py data.sqlite --table sessions --value minutes --group plan --unit account

Reads a CSV, JSON-lines or SQLite table: one row per measurement, a numeric value column and a group column.
Prints per group the sample size, mean, median, standard deviation, range and skew; the difference in means
(b minus a) with a bootstrap interval; a two-sided permutation test for that difference; and Cohen's d.
The seed is fixed (--seed), so the same data gives the same numbers on every run.

Assumptions: sample size, split between the groups, skew and unequal spread are checked from the data and
warned about in plain words. Independence is checked only when --unit names the column that identifies a
unit (a user, a patient, an account): each unit may appear once and in one group. Without --unit it is listed
under "could not check". When a group is too small the test is not run and the result is "not verified".

--claim states what the caller wants to say: differ, a-higher or b-higher. The claim passes only when the
permutation p-value is under alpha and the direction fits.

Exit codes: 0 = compared; samples large enough; independence checked; a stated claim is supported
            1 = a stated claim is not supported by the data, or a unit repeats or sits in both groups
            2 = not verified or blocked: a group is too small, independence unchecked, or unusable input
Thresholds come from references/limits.json and are printed with their status.
"""
import argparse
import csv
import io
import itertools
import json
import math
import os
import pathlib
import random
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
FALLBACK = {"min_n_test": 8, "small_n_warn": 30, "skew_warn": 1.0, "spread_ratio_warn": 2.0, "split_ratio_warn": 3.0,
            "alpha": 0.05, "bootstrap_resamples": 2000}


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


def skew(values):
    mean, n = statistics.fmean(values), len(values)
    m2 = sum((v - mean) ** 2 for v in values) / n
    return 0.0 if m2 == 0 else (sum((v - mean) ** 3 for v in values) / n) / m2 ** 1.5


def permutation_p(a, b, permutations, rng):
    """Two-sided p-value for the difference in means. Exact when every split can be listed, else sampled."""
    pooled, n_a, n = a + b, len(a), len(a) + len(b)
    total = sum(pooled)
    observed = abs(statistics.fmean(b) - statistics.fmean(a))

    def gap(sum_a):
        return abs((total - sum_a) / (n - n_a) - sum_a / n_a)

    if math.comb(n, n_a) <= permutations:
        splits = [gap(sum(combo)) for combo in itertools.combinations(pooled, n_a)]
        return sum(1 for g in splits if g >= observed - 1e-12) / len(splits), f"exact, all {len(splits)} splits"
    hits = 0
    for _ in range(permutations):
        rng.shuffle(pooled)
        hits += gap(sum(pooled[:n_a])) >= observed - 1e-12
    return (hits + 1) / (permutations + 1), f"{permutations} random splits"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", help="a CSV, JSON-lines or SQLite file with one row per measurement")
    parser.add_argument("--value", required=True, help="the numeric column to compare")
    parser.add_argument("--group", required=True, help="the column that says which group a row is in")
    parser.add_argument("--a", help="the first group (needed when the group column holds more than two values)")
    parser.add_argument("--b", help="the second group")
    parser.add_argument("--unit", help="the column that identifies a unit, to check independence")
    parser.add_argument("--table", help="table name for a SQLite file with more than one")
    parser.add_argument("--claim", choices=["differ", "a-higher", "b-higher"], help="the statement the data should support")
    parser.add_argument("--permutations", type=int, default=10000, help="random splits for the permutation test (default 10000)")
    parser.add_argument("--seed", type=int, default=20261122, help="seed for the permutation test and the bootstrap (default 20261122)")
    args = parser.parse_args()

    limits, limit_lines = load_limits()
    try:
        _, columns, rows, notes = load_table(args.file, args.table)
    except Blocked as exc:
        blocked(str(exc))
    absent = [c for c in (args.value, args.group, args.unit) if c and c not in columns]
    if absent:
        blocked(f"column(s) not in the data: {', '.join(absent)}. Columns: {', '.join(columns)}")
    if args.permutations < 100:
        blocked("--permutations must be at least 100")
    gi, vi = columns.index(args.group), columns.index(args.value)
    labels = sorted({str(row[gi]).strip() for row in rows if not is_empty(row[gi])})
    if bool(args.a) != bool(args.b):
        blocked("give both --a and --b, or neither")
    if args.a:
        if args.a == args.b or args.a not in labels or args.b not in labels:
            blocked(f"--a and --b must be two different values of {args.group}; it holds: {', '.join(labels[:20])}")
        name_a, name_b = args.a, args.b
    elif len(labels) == 2:
        name_a, name_b = labels
    else:
        blocked(f"{args.group} holds {len(labels)} groups ({', '.join(labels[:20])}); this script compares two. Name them with --a and --b.")

    report = Report()
    groups, left_out, units = {name_a: [], name_b: []}, [], {}
    for number, row in enumerate(rows, 1):
        label = "" if is_empty(row[gi]) else str(row[gi]).strip()
        if label not in groups:
            continue
        value = as_number(row[vi])
        if value is None:
            left_out.append(number)
            continue
        groups[label].append(value)
        if args.unit:
            units.setdefault(str(row[columns.index(args.unit)]).strip(), []).append(label)
    a, b = groups[name_a], groups[name_b]

    print(f"STAT COMPARE {args.file}: {args.value} by {args.group} (a = {name_a}, b = {name_b}); seed {args.seed}")
    for line in limit_lines:
        print(f"  note: {line}")
    print("\nGROUPS")
    for name, values in ((name_a, a), (name_b, b)):
        if values:
            spread = statistics.stdev(values) if len(values) > 1 else float("nan")
            print(f"  {name}: n {len(values)}, mean {statistics.fmean(values):.4g}, median {statistics.median(values):.4g}, "
                  f"sd {spread:.4g}, min {min(values):.4g}, max {max(values):.4g}, skew {skew(values):+.2f}")
        else:
            print(f"  {name}: n 0")
    if left_out:
        report.warn(f"{len(left_out)} row(s) left out because {args.value} is empty or not a number: rows {brief(left_out)}")
    if notes["ragged"] or notes["bad_lines"]:
        report.warn("the file has malformed rows or lines; run data-profile on it before trusting any comparison")

    if args.unit:
        repeated = sorted(u for u, seen in units.items() if len(seen) > 1 and len(set(seen)) == 1)
        crossed = sorted(u for u, seen in units.items() if len(set(seen)) > 1)
        if crossed:
            report.fail(f"{len(crossed)} unit(s) appear in both groups ({args.unit}: {', '.join(crossed[:5])}); the groups are not separate")
        if repeated:
            report.fail(f"{len(repeated)} unit(s) appear more than once ({args.unit}: {', '.join(repeated[:5])}); rows are not independent, so the p-value is too small. Use one row per unit.")
        if not crossed and not repeated:
            report.ok(f"independence: each {args.unit} appears once and in one group")
    else:
        report.skip("independence was not checked: name the column that identifies a unit with --unit (repeated measures of one unit make any p-value too small)")

    smallest = min(len(a), len(b))
    if smallest < limits["min_n_test"]:
        report.skip(f"the smaller group has {smallest} value(s), under the minimum of {limits['min_n_test']}: no test was run and no difference is claimed either way")
        print("\nRESULT OF THE COMPARISON: not verified, sample too small")
        return report.finish()

    rng = random.Random(args.seed)
    mean_a, mean_b = statistics.fmean(a), statistics.fmean(b)
    diff = mean_b - mean_a
    p_value, how = permutation_p(list(a), list(b), args.permutations, rng)
    sd_a, sd_b = statistics.stdev(a), statistics.stdev(b)
    pooled_sd = math.sqrt(((len(a) - 1) * sd_a ** 2 + (len(b) - 1) * sd_b ** 2) / (len(a) + len(b) - 2))
    boots = sorted(statistics.fmean(rng.choices(b, k=len(b))) - statistics.fmean(rng.choices(a, k=len(a)))
                   for _ in range(int(limits["bootstrap_resamples"])))
    low, high = boots[int(0.025 * len(boots))], boots[int(0.975 * len(boots)) - 1]
    print("\nCOMPARISON")
    print(f"  difference in means (b - a): {diff:+.4g}" + (f"  ({diff / mean_a:+.1%} of a)" if mean_a else ""))
    print(f"  95% bootstrap interval for the difference: {low:+.4g} to {high:+.4g} ({len(boots)} resamples)")
    print(f"  permutation test, two-sided: p = {p_value:.4g} ({how})")
    print("  effect size, Cohen's d: " + (f"{diff / pooled_sd:+.2f}" if pooled_sd else "undefined (no spread in either group)"))
    evidence = p_value < limits["alpha"]
    print(f"  reading: {'evidence of a difference' if evidence else 'no evidence of a difference; this is not proof that the groups are equal'} at alpha {limits['alpha']}")
    print("  the p-value says whether the difference could be chance; the difference and its interval say whether it matters")

    if smallest < limits["small_n_warn"]:
        report.warn(f"small sample: the smaller group has {smallest} values (under {limits['small_n_warn']}); the interval is wide and one or two rows can change the result")
    else:
        report.ok(f"sample size: both groups have at least {limits['small_n_warn']} values")
    ratio = max(len(a), len(b)) / smallest
    if ratio > limits["split_ratio_warn"]:
        report.warn(f"lopsided split: {len(a)} against {len(b)} rows ({ratio:.1f} to 1); check how rows were assigned to groups")
    else:
        report.ok(f"split: {len(a)} and {len(b)} rows")
    skewed = [f"{name} {skew(values):+.2f}" for name, values in ((name_a, a), (name_b, b)) if abs(skew(values)) > limits["skew_warn"]]
    if skewed:
        report.warn(f"heavy skew ({', '.join(skewed)}): a few large values drive the means; compare the medians above too")
    else:
        report.ok(f"skew: both groups within +/-{limits['skew_warn']}")
    if min(sd_a, sd_b) == 0 or max(sd_a, sd_b) / min(sd_a, sd_b) > limits["spread_ratio_warn"]:
        report.warn(f"unequal spread (sd {sd_a:.4g} against {sd_b:.4g}): the groups differ in more than their means, so a small p-value may reflect spread, not level")
    else:
        report.ok(f"spread: standard deviations within {limits['spread_ratio_warn']} to 1")

    if args.claim:
        fits = evidence and (args.claim == "differ" or (args.claim == "b-higher") == (diff > 0))
        wording = {"differ": "the groups differ", "a-higher": f"{name_a} is higher than {name_b}", "b-higher": f"{name_b} is higher than {name_a}"}[args.claim]
        if fits:
            report.ok(f"claim '{wording}' is supported: difference {diff:+.4g}, p = {p_value:.4g}")
        else:
            report.fail(f"claim '{wording}' is not supported: difference {diff:+.4g}, p = {p_value:.4g}, alpha {limits['alpha']}")
    return report.finish()


if __name__ == "__main__":
    sys.exit(main())

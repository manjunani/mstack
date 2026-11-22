#!/usr/bin/env python3
"""Run one read-only SQL statement with limits that live in this runner, not in the prompt.

  run.py --db data.sqlite --sql "SELECT ..."            run on a SQLite file
  run.py --db data.sqlite --file query.sql --limit 50   read the statement from a file
  run.py --dialect postgres --file query.sql            check only; print the statement for your own client

For SQLite the script: refuses anything but a single SELECT or WITH statement; opens the file read-only
(URI mode=ro, query_only, and an authorizer that denies every write); prints the query plan; stops fetching
after the row limit; interrupts the statement at the time limit; prints the rows and a hash of the result.
For every other dialect it makes no connection. It checks the text is one read-only statement, adds a row
limit when the statement has none, and prints it for the user to run with their own client and read-only role.

The report keeps three lists apart: findings, checked and fine, could not check.
Exit codes: 0 = the statement ran inside the limits
            1 = refused (not a single read-only statement), stopped at the time limit, or the database rejected it
            2 = not verified or blocked: no database given, the file is not SQLite, or a dialect that is not run here
--log appends one JSON line (time, statement, row count, result hash) to the file named; no rows are logged.
"""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import re
import sqlite3
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

LIMITS_FILE = pathlib.Path(__file__).resolve().parent.parent / "references" / "limits.json"
FALLBACK = {"row_limit": 200, "time_limit_seconds": 5, "cell_width": 60}


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


def cell(value, width):
    if value is None:
        return "NULL"
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    text = str(value).replace("\n", " ").replace("\r", " ")
    return text if len(text) <= width else text[:width - 1] + "…"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", help="path of the SQLite file (needed when the dialect is sqlite)")
    parser.add_argument("--sql", help="the statement")
    parser.add_argument("--file", help="a file holding the statement")
    parser.add_argument("--dialect", default="sqlite", choices=["sqlite", "postgres", "mysql", "mssql", "bigquery", "snowflake", "other"],
                        help="sqlite is run here; every other dialect is checked and printed, never connected to")
    parser.add_argument("--limit", type=int, help="most rows to fetch (default from references/limits.json)")
    parser.add_argument("--timeout", type=float, help="seconds before the statement is interrupted (default from references/limits.json)")
    parser.add_argument("--max-width", type=int, help="widest cell to print before it is cut")
    parser.add_argument("--log", help="append one JSON line about this run to this file")
    args = parser.parse_args()

    if bool(args.sql) == bool(args.file):
        blocked("give the statement with exactly one of --sql or --file")
    if args.file:
        try:
            sql = pathlib.Path(args.file).read_text(encoding="utf-8")
        except OSError as exc:
            blocked(f"cannot read {args.file}: {exc.strerror}")
    else:
        sql = args.sql
    limits, limit_lines = load_limits()
    row_limit = args.limit if args.limit is not None else limits["row_limit"]
    seconds = args.timeout if args.timeout is not None else limits["time_limit_seconds"]
    width = args.max_width or limits["cell_width"]
    if row_limit < 1 or seconds <= 0:
        blocked("--limit must be at least 1 and --timeout above 0")

    report = Report()
    statement, skeleton, problems = read_only_problems(sql, brackets=args.dialect in ("sqlite", "mssql"))
    print(f"SQL RUN ({args.dialect}), row limit {row_limit}, time limit {seconds:g}s")
    for line in limit_lines:
        if (args.limit is None and line.startswith("row_limit")) or (args.timeout is None and line.startswith("time_limit")):
            print(f"  note: {line}")
    if problems:
        for problem in problems:
            report.fail(f"refused: {problem}")
        return report.finish("the statement was refused and nothing was run")
    report.ok("exactly one statement")
    report.ok("it starts with SELECT or WITH and holds no write keyword outside quotes (a text check; see the read-only layer below)")

    if args.dialect != "sqlite":
        if has_row_limit(skeleton):
            shown = statement
            report.ok("the statement carries its own row limit")
        elif args.dialect == "mssql":
            shown = statement
            report.warn(f"no row limit in the statement; for SQL Server add TOP {row_limit} yourself before running it")
        else:
            shown = f"{statement}\nLIMIT {row_limit}"
            report.ok(f"row limit added: LIMIT {row_limit}")
        print("\nSTATEMENT FOR YOUR OWN CLIENT (not run here)")
        print("\n".join("  " + line for line in shown.splitlines()))
        report.skip(f"the statement was not run: this script connects to SQLite files only, never to {args.dialect}")
        report.skip("the query plan and the cost were not read; a row limit bounds the rows returned, not the rows scanned")
        report.skip("whether the connection is read-only: use a role that cannot write, and a statement timeout, in your own client")
        return report.finish()

    if not args.db:
        blocked("--db <file> is needed to run on SQLite")
    if not os.path.isfile(args.db):
        blocked(f"no such file: {args.db}")
    if not is_sqlite_file(args.db):
        blocked(f"{args.db} is not a SQLite database file")
    try:
        conn = open_read_only(args.db)
        report.ok("database opened read-only (mode=ro, query_only, write actions denied by the authorizer)")
        plan = conn.execute("EXPLAIN QUERY PLAN " + statement).fetchall()
    except sqlite3.Error as exc:
        report.fail(f"SQLite rejected the statement: {exc}")
        return report.finish("the database rejected the statement")
    print("\nQUERY PLAN")
    for row in plan:
        print(f"  {row[-1]}")

    set_time_limit(conn, seconds)
    started = time.monotonic()
    try:
        cursor = conn.execute(statement)
        names = [d[0] for d in cursor.description or []]
        fetched = cursor.fetchmany(row_limit + 1)
    except sqlite3.Error as exc:
        took = time.monotonic() - started
        if "interrupt" in str(exc).lower():
            report.fail(f"stopped after the {seconds:g}s time limit; no rows are reported")
            return report.finish("the statement ran past the time limit")
        report.fail(f"SQLite rejected the statement after {took:.2f}s: {exc}")
        return report.finish("the database rejected the statement")
    finally:
        conn.set_progress_handler(None, 0)
    took = time.monotonic() - started
    truncated = len(fetched) > row_limit
    rows = fetched[:row_limit]
    conn.close()

    digest = hashlib.sha256(repr((names, rows)).encode("utf-8", "replace")).hexdigest()[:16]
    print(f"\nROWS ({len(rows)}{' shown, more exist' if truncated else ''}; {took:.2f}s; result hash {digest})")
    print("  " + " | ".join(names))
    for row in rows:
        print("  " + " | ".join(cell(v, width) for v in row))
    report.ok(f"finished in {took:.2f}s, inside the {seconds:g}s time limit")
    if truncated:
        report.warn(f"more than {row_limit} rows match; only the first {row_limit} were fetched, so totals worked out from these rows are partial")
    else:
        report.ok(f"{len(rows)} row(s), under the row limit of {row_limit}")
    if not rows:
        report.warn("the statement returned no rows; check the filter before reading zero as an answer")
    if args.log:
        entry = {"time": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "db": args.db,
                 "statement": statement, "rows": len(rows), "truncated": truncated, "result_hash": digest}
        with open(args.log, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
        print(f"\nlogged to {args.log}")
    return report.finish()


if __name__ == "__main__":
    sys.exit(main())

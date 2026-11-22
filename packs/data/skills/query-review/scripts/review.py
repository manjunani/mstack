#!/usr/bin/env python3
"""Review one SELECT statement: its risky shapes, and on SQLite its real query plan. Read-only.

  review.py --file query.sql --db data.sqlite          text checks plus EXPLAIN QUERY PLAN on the SQLite file
  review.py --sql "SELECT ..." --dialect postgres      text checks only; no connection is made
  review.py --file query.sql --db data.sqlite --purpose production --large-rows 50000

Text checks (every dialect): SELECT *, a JOIN with no ON or USING, tables joined with a comma and no linking
condition, CROSS and NATURAL joins, a filter that wraps a column in a function, LIKE with a leading wildcard,
NOT IN with a subquery, and no row limit on an exploratory query.
Plan checks (SQLite only): a full scan of a large table, a filter that uses no index, an index SQLite has to
build on every run, and a sort done in a temporary structure. The statement itself is never executed; only
EXPLAIN QUERY PLAN and a row count per scanned table are, on a read-only connection with a time limit.

The report keeps three lists apart: findings, checked and fine, could not check.
Exit codes: 0 = no blocking finding (warnings may be listed) and the plan was read
            1 = a blocking finding: a join with no condition, or a full scan of a large table
            2 = not verified or blocked: no plan was read (no database, or another dialect), or the input is unusable
"""
import argparse
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
FALLBACK = {"large_table_rows": 10000, "count_seconds": 5}
STOP = r"\b(where|group|order|limit|union|intersect|except|having|window|join|inner|left|right|full|cross|natural|on|using)\b"
AGGREGATE = re.compile(r"\b(count|sum|avg|min|max|total|group_concat|string_agg|array_agg)\s*\(")
NOT_FUNCTIONS = {"exists", "not", "any", "all", "select", "in", "and", "or", "on", "where", "values"}


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


def level(text, start):
    """The text from start to the end of its own parenthesis level, with deeper levels blanked."""
    depth, out = 0, []
    for ch in text[start:]:
        if ch == "(":
            depth += 1
            out.append(" ")
        elif ch == ")":
            depth -= 1
            if depth < 0:
                break
            out.append(" ")
        else:
            out.append(ch if depth == 0 else " ")
    return "".join(out)


def clause(flat, stops=STOP):
    """The start of a flattened text, up to the first stop keyword."""
    match = re.search(stops, flat)
    return flat[:match.start()] if match else flat


def text_checks(statement, sk, purpose, report):
    """sk is the lower-case skeleton: comments gone, insides of strings and quoted names blanked."""
    if re.search(r"\bselect\s+(distinct\s+)?(\w+\.)?\*", sk) or re.search(r",\s*(\w+\.)?\*\s*(,|\bfrom\b)", sk):
        report.warn("SELECT * returns every column: the result changes when the table does, and more is read than is used")
    else:
        report.ok("columns are named (no SELECT *)")

    joins = list(re.finditer(r"\bjoin\b", sk))
    bare = 0
    for match in joins:
        before = sk[:match.start()].split()[-2:]
        rest = level(sk, match.end())
        target = clause(rest, r"\b(where|group|order|limit|union|intersect|except|having|window|join|inner|left|right|full|cross|natural)\b")
        name = (re.findall(r"[\w.]+", target) or ["?"])[0]
        if "cross" in before:
            report.warn(f"CROSS JOIN with {name}: every row is paired with every row; confirm that is meant")
        elif "natural" in before:
            report.warn(f"NATURAL JOIN with {name}: the join columns are picked by name and change silently when a column is added")
        elif not re.search(r"\b(on|using)\b", target):
            bare += 1
            report.fail(f"JOIN with {name} has no ON or USING: every row is paired with every row")
    if joins and not bare:
        report.ok(f"{len(joins)} JOIN(s), each with a condition or stated as CROSS or NATURAL")

    for match in re.finditer(r"\bfrom\b", sk):
        scope = level(sk, match.end())
        tables = clause(scope)
        if "," not in tables:
            continue
        where = re.search(r"\bwhere\b", scope)
        names = ", ".join(part.split()[0] for part in tables.split(",") if part.split())
        if not where:
            report.fail(f"tables joined with a comma and no WHERE ({names}): every row is paired with every row")
        else:
            body = clause(scope[where.end():], r"\b(group|order|limit|union|intersect|except|having|window)\b")
            links = [m for m in re.finditer(r"(\w+)\.\w+\s*=\s*(\w+)\.\w+", body) if m.group(1) != m.group(2)]
            if links:
                report.ok(f"comma join ({names}) is linked in WHERE")
            else:
                report.warn(f"tables joined with a comma ({names}) and no condition linking them was found in WHERE")

    wrapped = set()
    for match in re.finditer(r"\b(where|and|or|on)\s+(?:not\s+)?(\w+)\s*\(\s*([\w.]+)[^()]*\)\s*(=|<>|!=|<=|>=|<|>|\blike\b|\bin\b|\bbetween\b|\bis\b)", sk):
        function, column = match.group(2), match.group(3)
        if function not in NOT_FUNCTIONS and not column.isdigit() and (function, column) not in wrapped:
            wrapped.add((function, column))
            report.warn(f"filter wraps {column} in {function}(): an ordinary index on {column} cannot serve it; compare the bare column, or index the expression")
    if not wrapped and re.search(r"\b(where|on)\b", sk):
        report.ok("no filter wraps a column in a function")

    if re.search(r"\blike\s+'%", statement.lower()):
        report.warn("LIKE with a leading % cannot use an ordinary index and reads every row")
    if re.search(r"\bnot\s+in\s*\(\s*select\b", sk):
        report.warn("NOT IN with a subquery returns no rows at all when the subquery yields a NULL; NOT EXISTS does not have that trap")

    first_from = re.search(r"\bfrom\b", level(sk, 0))
    select_list = level(sk, 0)[:first_from.start()] if first_from else level(sk, 0)
    one_row = bool(AGGREGATE.search(sk[:len(select_list)])) and "group" not in top_level_words(sk)
    if has_row_limit(sk):
        report.ok("the statement has a row limit")
    elif one_row:
        report.ok("no row limit needed: an aggregate with no GROUP BY returns one row")
    elif purpose == "exploratory":
        report.warn("no LIMIT on an exploratory query: add one, or the client fetches every matching row")
    else:
        report.ok("no row limit, accepted because --purpose production was given")


def alias_map(sk):
    names = {}
    for match in re.finditer(r"\b(?:from|join)\s+([\w.]+)(?:\s+(?:as\s+)?(\w+))?", sk):
        table, alias = match.group(1).split(".")[-1], match.group(2)
        names[table] = table
        if alias and not re.fullmatch(STOP.strip(r"\b"), alias):
            names[alias] = table
    return names


def plan_checks(db, statement, sk, limits, large, report):
    try:
        conn = open_read_only(db)
        plan = [row[-1] for row in conn.execute("EXPLAIN QUERY PLAN " + statement)]
        tables = {r[0].lower(): r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    except sqlite3.Error as exc:
        report.skip(f"the query plan was not read: SQLite rejected the statement ({exc})")
        return
    print("\nQUERY PLAN")
    for line in plan:
        print(f"  {line}")
    aliases, counts = alias_map(sk), {}

    def rows_of(name):
        table = tables.get(aliases.get(name.lower(), name.lower()))
        if table is None:
            return None, name
        if table not in counts:
            set_time_limit(conn, limits["count_seconds"])
            try:
                counts[table] = conn.execute('SELECT count(*) FROM "' + table.replace('"', '""') + '"').fetchone()[0]
            except sqlite3.Error:
                counts[table] = None
                report.skip(f"the size of {table} was not counted within {limits['count_seconds']}s")
            conn.set_progress_handler(None, 0)
        return counts[table], table

    filtered = "where" in top_level_words(sk) or bool(re.search(r"\bon\b", sk))
    any_large = False
    for line in plan:
        match = re.match(r"(SCAN|SEARCH)\s+(?:TABLE\s+)?(\S+)", line)
        if "AUTOMATIC" in line and match:
            report.warn(f"SQLite builds a temporary index on {rows_of(match.group(2))[1]} every time this runs ({line.strip()}): a permanent index is missing")
        elif match and match.group(1) == "SEARCH":
            report.ok(f"index used: {line.strip()}")
        elif match:
            count, table = rows_of(match.group(2))
            using_index = " USING " in line
            if count is None:
                report.skip(f"'{line.strip()}': {table} is not a plain table here, so its size was not read")
            elif count >= large:
                any_large = True
                what = "reads the whole index" if using_index else "full scan"
                tail = "; no index serves the filter" if filtered and not using_index else ""
                (report.warn if using_index else report.fail)(f"{what} of {table} ({count} rows, large-table line {large}){tail}")
            else:
                report.ok(f"scan of {table} is small ({count} rows, large-table line {large})")
        elif "TEMP B-TREE" in line:
            (report.warn if any_large or any((c or 0) >= large for c in counts.values()) else report.ok)(
                f"sort or grouping done in a temporary structure ({line.strip()})")
    conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sql", help="the statement")
    parser.add_argument("--file", help="a file holding the statement")
    parser.add_argument("--db", help="a SQLite file to read the query plan from")
    parser.add_argument("--dialect", default="sqlite", choices=["sqlite", "postgres", "mysql", "mssql", "bigquery", "snowflake", "other"])
    parser.add_argument("--purpose", default="exploratory", choices=["exploratory", "production"],
                        help="exploratory (default) expects a row limit; production does not")
    parser.add_argument("--large-rows", type=int, help="a table with at least this many rows is large (default from references/limits.json)")
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
    statement, skeleton, problems = read_only_problems(sql, brackets=args.dialect in ("sqlite", "mssql"))
    if problems:
        blocked("this script reviews one SELECT or WITH statement: " + "; ".join(problems))
    limits, limit_lines = load_limits()
    large = args.large_rows if args.large_rows is not None else limits["large_table_rows"]

    report = Report()
    print(f"QUERY REVIEW ({args.dialect}, {args.purpose})")
    text_checks(statement, skeleton.lower(), args.purpose, report)
    if args.dialect != "sqlite":
        report.skip(f"the query plan was not read: this script does not connect to {args.dialect}; run EXPLAIN in your own client and read it beside these findings")
    elif not args.db:
        report.skip("the query plan was not read: no SQLite file was given with --db")
    elif not is_sqlite_file(args.db):
        blocked(f"{args.db} is not a readable SQLite database file")
    else:
        for line in limit_lines:
            if args.large_rows is None or not line.startswith("large_table_rows"):
                print(f"  note: {line}")
        plan_checks(args.db, statement, skeleton.lower(), limits, large, report)
    return report.finish()


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Run every mstack-data script on small throwaway datasets and compare each exit code with the expected one.

  data_cases.py <path to packs/data> <parent folder> [--only SKILL]

For each skill a NEW folder <parent>/data-<skill>/ is made (the run refuses if it exists) and filled with
fixtures built here with the standard library: CSV, JSON-lines, SQLite, .xlsx and .ipynb files.
Each case prints one line: ok or BAD, the label, the exit code and the expected one. A case can also require
text in the output, or forbid it. The script exits 1 when any case is wrong.

Nothing outside <parent> is written. No network, no installs. The notebook re-run cases use a stub program
named `jupyter` made in the fixture folder; real Jupyter is never called by this file.
"""
import argparse
import csv
import hashlib
import json
import os
import pathlib
import random
import sqlite3
import stat
import subprocess
import sys
import zipfile

RESULTS = {"run": 0, "wrong": 0}


def case(label, script, argv, want, has=(), lacks=(), env=None, cwd=None):
    """Run one script once; print ok or BAD; return the output."""
    done = subprocess.run([sys.executable, "-B", str(script)] + [str(a) for a in argv], capture_output=True, text=True,
                          env=env, cwd=cwd, timeout=120)
    out = done.stdout + done.stderr
    lines = [line for line in done.stdout.strip().splitlines() if line.strip()]
    problems = []
    if done.returncode != want:
        problems.append(f"want exit {want}")
    if not lines or not lines[-1].startswith(("RESULT pass", "RESULT fail: ", "RESULT not verified: ", "blocked: ")):
        problems.append("last line is not a RESULT or blocked line")
    elif {0: "RESULT pass", 1: "RESULT fail"}.get(done.returncode, "") not in lines[-1]:
        problems.append(f"last line does not fit exit {done.returncode}: {lines[-1][:60]}")
    problems += [f"missing text: {text!r}" for text in has if text not in out]
    problems += [f"forbidden text present: {text!r}" for text in lacks if text in out]
    RESULTS["run"] += 1
    RESULTS["wrong"] += bool(problems)
    print(f"{'BAD ' if problems else 'ok  '}{label}: exit {done.returncode}" + ("  <- " + "; ".join(problems) if problems else ""))
    if problems:
        print("      " + "\n      ".join(out.strip().splitlines()[-12:]))
    return out


def expect(label, condition, detail=""):
    RESULTS["run"] += 1
    RESULTS["wrong"] += not condition
    print(f"{'ok  ' if condition else 'BAD '}{label}" + (f"  <- {detail}" if detail and not condition else ""))


def write_csv(path, header, rows, **kwargs):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, **kwargs)
        writer.writerow(header)
        writer.writerows(rows)


def digest(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def write_json(path, data):
    pathlib.Path(path).write_text(json.dumps(data, indent=1), encoding="utf-8")


def make_shop(path, orders=500, index=True):
    """A SQLite file: customers (50 rows) and orders, with a fixed seed."""
    rng = random.Random(11)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, country TEXT)")
    conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER, status TEXT, amount REAL, created_at TEXT)")
    conn.executemany("INSERT INTO customers VALUES (?, ?, ?)", [(i, f"customer {i}", rng.choice(["IN", "DE", "US"])) for i in range(1, 51)])
    conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?)",
                     [(i, rng.randint(1, 50), rng.choice(["paid", "paid", "paid", "new", "refunded"]), round(rng.uniform(5, 200), 2),
                       f"2026-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}") for i in range(1, orders + 1)])
    if index:
        conn.execute("CREATE INDEX idx_orders_customer ON orders (customer_id)")
    conn.commit()
    conn.close()


# ---------------------------------------------------------------- data-profile
def profile_cases(pack, folder):
    script = pack / "skills/data-profile/scripts/profile.py"
    rows = [[i, f"user{i}@example.com", f"2026-01-{i:02d}", f"{i * 1.5:.2f}", "paid"] for i in range(1, 12)]
    rows[2][3] = "N/A"
    rows[3][3] = "abc"
    rows[4][4] = " paid "
    rows.append(list(rows[10]))
    write_csv(folder / "people.csv", ["id", "email", "signup", "amount", "status"], rows)
    before = digest(folder / "people.csv")
    out = case("people.csv: warnings only", script, [folder / "people.csv"], 0,
               has=["12 rows, 5 columns", "1 exact duplicate row(s): rows 12", "mostly float but 1 value(s) are another type: rows 4",
                    "1 value(s) such as N/A", "looks like personal data", "spaces at the start or end", "looks like an identifier but 1 value(s) repeat",
                    "top: hidden"],
               lacks=["user1@example.com"])
    expect("people.csv: the three lists are printed", all(t in out for t in ("FINDINGS (", "CHECKED AND FINE (", "COULD NOT CHECK (")))
    case("people.csv --show-personal prints values", script, [folder / "people.csv", "--show-personal"], 0, has=["user11@example.com"])
    expect("people.csv is unchanged after profiling", digest(folder / "people.csv") == before)

    write_csv(folder / "tidy.csv", ["item", "qty", "price", "added"],
              [["bolt", 4, 0.25, "2026-02-01"], ["nut", 9, 0.1, "2026-02-02"], ["washer", 2, 0.05, "2026-02-03"], ["rivet", 7, 0.3, "2026-02-03"]])
    case("tidy.csv: nothing to report", script, [folder / "tidy.csv"], 0, has=["FINDINGS (0)", "4 rows, 4 columns", "min 2.0  max 9.0", "added: date"], lacks=["personal data?"])

    (folder / "ragged.csv").write_text("a,b,c\n1,2,3\n4,5\n6,7,8,9\n", encoding="utf-8")
    case("ragged.csv: wrong field counts fail", script, [folder / "ragged.csv"], 1, has=["2 row(s) have the wrong number of fields: rows 2, 3"])
    (folder / "header_only.csv").write_text("a,b,c\n", encoding="utf-8")
    case("header_only.csv: zero rows fail", script, [folder / "header_only.csv"], 1, has=["no data rows"])
    (folder / "zero_bytes.csv").write_text("", encoding="utf-8")
    case("zero_bytes.csv: blocked", script, [folder / "zero_bytes.csv"], 2, has=["is empty"])
    case("missing file: blocked", script, [folder / "nope.csv"], 2, has=["cannot read"])

    (folder / "events.jsonl").write_text('{"id": 1, "kind": "open", "ms": 12.5}\n{"id": 2, "kind": "close"}\nnot json\n{"id": 3, "kind": "open", "ms": 7}\n', encoding="utf-8")
    case("events.jsonl: a bad line fails", script, [folder / "events.jsonl"], 1, has=["type jsonl", "1 line(s) are not a JSON object: lines 3"])
    (folder / "good.jsonl").write_text('{"id": 1, "kind": "open", "ms": 12.5}\n{"id": 2, "kind": "close", "ms": 3}\n', encoding="utf-8")
    case("good.jsonl: pass", script, [folder / "good.jsonl"], 0, has=["type jsonl", "2 rows, 3 columns"])

    (folder / "latin.csv").write_bytes("city,visits\nK\xf6ln,3\nMalm\xf6,5\n".encode("latin-1"))
    case("latin.csv: not UTF-8 is a warning", script, [folder / "latin.csv"], 0, has=["not valid UTF-8"])
    (folder / "dates.tsv").write_text("ref\twhen\nA1\t03/04/2026\nA2\t11/04/2026\nA3\t25/04/2026\n", encoding="utf-8")
    case("dates.tsv: tab-separated, non-ISO dates warned", script, [folder / "dates.tsv"], 0, has=["3 rows, 2 columns", "not in ISO form"])

    make_shop(folder / "shop.sqlite")
    case("shop.sqlite without --table: blocked", script, [folder / "shop.sqlite"], 2, has=["holds 2 tables (customers, orders)"])
    case("shop.sqlite --table orders", script, [folder / "shop.sqlite", "--table", "orders"], 0, has=["type sqlite", "500 rows, 5 columns", "identifier-like"])
    case("shop.sqlite --table nope: blocked", script, [folder / "shop.sqlite", "--table", "nope"], 2, has=["no table 'nope'"])
    case("--max-rows leaves rows unread: not verified", script, [folder / "shop.sqlite", "--table", "orders", "--max-rows", "100"], 2,
         has=["rows after the first 100 were not read"])
    with zipfile.ZipFile(folder / "book.xlsx", "w") as archive:
        archive.writestr("xl/workbook.xml", "<workbook/>")
    case("an .xlsx file: blocked", script, [folder / "book.xlsx"], 2, has=["zip container"])
    case("--json writes a new file", script, [folder / "tidy.csv", "--json", folder / "tidy.profile.json"], 0, has=["full profile written"])
    profile = json.loads((folder / "tidy.profile.json").read_text(encoding="utf-8"))
    expect("the JSON profile holds 4 columns and the three lists", len(profile["columns"]) == 4 and {"findings", "checked_and_fine", "could_not_check"} <= set(profile))
    case("--json refuses to overwrite", script, [folder / "tidy.csv", "--json", folder / "tidy.profile.json"], 2, has=["already exists"])


# ---------------------------------------------------------------- data-check
def check_cases(pack, folder):
    script = pack / "skills/data-check/scripts/check.py"
    write_csv(folder / "customers.csv", ["id", "name"], [[1, "Asha"], [2, "Ben"], [3, "Chen"]])
    write_csv(folder / "orders.csv", ["id", "customer_id", "status", "amount", "email"],
              [[1, 1, "paid", 20, "a@x.org"], [2, 2, "new", 35.5, "b@x.org"], [3, 9, "paid", -4, "c@x.org"],
               [3, 1, "lost", 80, "not-an-email"], ["", 2, "paid", 7000, ""], [6, 3, "paid", 12, "f@x.org"]])
    write_csv(folder / "orders_good.csv", ["id", "customer_id", "status", "amount", "email"],
              [[1, 1, "paid", 20, "a@x.org"], [2, 2, "new", 35.5, "b@x.org"], [3, 3, "paid", 12, ""]])
    rules = [{"type": "not_null", "column": "id"}, {"type": "unique", "columns": ["id"]},
             {"type": "in_set", "column": "status", "values": ["paid", "new", "refunded"]},
             {"type": "range", "column": "amount", "min": 0, "max": 5000},
             {"type": "pattern", "column": "email", "regex": "[^@\\s]+@[^@\\s]+\\.[a-z]+"},
             {"type": "row_count", "min": 1, "max": 100},
             {"name": "order has a customer", "type": "foreign_key", "column": "customer_id", "ref": "customers.csv", "ref_column": "id"}]
    write_json(folder / "rules_bad.json", {"dataset": "orders.csv", "rules": rules})
    write_json(folder / "rules_good.json", {"dataset": "orders_good.csv", "rules": rules})
    before = digest(folder / "orders.csv")
    case("every rule type fails where it should, with row numbers", script, [folder / "rules_bad.json"], 1,
         has=["[fail] not_null id: 1 empty value(s); rows 5", "[fail] unique id: 1 row(s) repeat an earlier key; rows 4",
              "[fail] in_set status: 1 value(s) outside the set; rows 4", "outside the range or not comparable; rows 3, 5",
              "[fail] pattern email: 1 value(s) do not match; rows 4", "[pass] row_count: 6 rows",
              "[fail] order has a customer: 1 value(s) not found in customers.csv.id; rows 3", "RESULT fail: 6 hard failure(s)"])
    case("the same rules pass on good data", script, [folder / "rules_good.json"], 0, has=["FINDINGS (0)", "CHECKED AND FINE (7)"])
    expect("orders.csv is unchanged after checking", digest(folder / "orders.csv") == before)

    write_json(folder / "rules_soft.json", {"dataset": "orders.csv", "rules": [
        {"type": "range", "column": "amount", "min": 0, "severity": "soft"}, {"type": "row_count", "min": 1}]})
    case("a soft rule that fails warns and does not fail the run", script, [folder / "rules_soft.json"], 0, has=["[warn] rule 1", "(soft rule)"])
    write_json(folder / "rules_notrun.json", {"dataset": "orders_good.csv", "rules": [
        {"type": "not_null", "column": "nope"}, {"type": "pattern", "column": "email", "regex": "(["},
        {"type": "foreign_key", "column": "customer_id", "ref": "missing.csv", "ref_column": "id"}, {"type": "between", "column": "amount"}]})
    case("rules that cannot run: not verified", script, [folder / "rules_notrun.json"], 2,
         has=["column(s) not in the dataset: nope", "the regex does not compile", "reference not readable", "unknown rule type 'between'", "COULD NOT CHECK (4)"])

    (folder / "none.csv").write_text("id,amount\n", encoding="utf-8")
    write_json(folder / "rules_empty.json", {"dataset": "none.csv", "rules": [{"type": "unique", "column": "id"}]})
    case("zero rows fail even when every rule passes", script, [folder / "rules_empty.json"], 1, has=["the dataset has zero rows"])
    write_json(folder / "rules_empty_ok.json", {"dataset": "none.csv", "rules": [{"type": "unique", "column": "id"}, {"type": "row_count", "min": 0}]})
    case("zero rows allowed by a row_count rule with min 0", script, [folder / "rules_empty_ok.json"], 0)

    case("--quarantine writes failing rows", script, [folder / "rules_bad.json", "--quarantine", folder / "bad_rows.csv"], 1, has=["7 failing row entries written"])
    with open(folder / "bad_rows.csv", encoding="utf-8", newline="") as handle:
        held = list(csv.reader(handle))
    expect("the quarantine file has a header and 7 entries with the rule name", len(held) == 8 and held[0][:2] == ["row", "rule"] and all(r[1] for r in held[1:]))
    case("--quarantine refuses to overwrite", script, [folder / "rules_bad.json", "--quarantine", folder / "bad_rows.csv"], 2, has=["already exists"])
    (folder / "broken.json").write_text("{not json", encoding="utf-8")
    case("a rules file that is not JSON: blocked", script, [folder / "broken.json"], 2, has=["not valid JSON"])
    write_json(folder / "norules.json", {"dataset": "orders.csv", "rules": []})
    case("an empty rules list: blocked", script, [folder / "norules.json"], 2, has=["non-empty 'rules' list"])

    make_shop(folder / "shop.sqlite")
    write_json(folder / "rules_sqlite.json", {"dataset": {"path": "shop.sqlite", "table": "orders"}, "rules": [
        {"type": "unique", "column": "id"}, {"type": "range", "column": "amount", "min": 5, "max": 200},
        {"type": "range", "column": "created_at", "min": "2026-01-01", "max": "2026-12-31"},
        {"type": "foreign_key", "column": "customer_id", "ref": {"path": "shop.sqlite", "table": "customers"}, "ref_column": "id"}]})
    case("a SQLite table with a foreign key into another table", script, [folder / "rules_sqlite.json"], 0, has=["500 rows", "CHECKED AND FINE (4)"])


# ---------------------------------------------------------------- sql-run
def sql_cases(pack, folder):
    script = pack / "skills/sql-run/scripts/run.py"
    db = folder / "shop.sqlite"
    make_shop(db)
    before = digest(db)
    run = lambda label, sql, want, **kw: case(label, script, ["--db", db, "--sql", sql] + kw.pop("more", []), want, **kw)
    run("a plain SELECT runs", "SELECT id, name FROM customers WHERE id <= 3", 0, has=["QUERY PLAN", "ROWS (3;", "1 | customer 1", "result hash"])
    run("the row limit stops the fetch", "SELECT * FROM orders", 0, more=["--limit", "5"], has=["ROWS (5 shown, more exist", "more than 5 rows match"])
    run("WITH is allowed", "WITH big AS (SELECT * FROM orders WHERE amount > 150) SELECT count(*) AS n FROM big", 0, has=["ROWS (1;"])
    run("a trailing semicolon is one statement", "SELECT count(*) FROM orders;", 0, has=["500"])
    run("a write keyword inside a string is not a write", "SELECT 'drop table orders; delete' AS note", 0, has=["drop table orders; delete"])
    run("replace() the function is allowed", "SELECT replace(name, 'customer', 'c') FROM customers LIMIT 2", 0, has=["c 1"])
    run("a write hidden in a comment is removed, not run", "SELECT 1 AS one -- ; DELETE FROM orders", 0, has=["ROWS (1;"])
    run("zero rows is reported as a warning", "SELECT id FROM orders WHERE amount < 0", 0, has=["returned no rows"])
    run("DELETE is refused", "DELETE FROM orders", 1, has=["starts with DELETE", "nothing was run"])
    run("two statements are refused", "SELECT 1; DROP TABLE orders", 1, has=["2 statements found"])
    run("UPDATE after a comment is refused", "/* tidy */ UPDATE orders SET amount = 0", 1, has=["starts with UPDATE"])
    run("PRAGMA is refused", "PRAGMA table_info(orders)", 1, has=["starts with PRAGMA"])
    run("a write inside WITH is refused", "WITH gone AS (DELETE FROM orders RETURNING id) SELECT * FROM gone", 1, has=["keyword DELETE"])
    run("an unclosed quote is refused", "SELECT 'oops FROM orders", 1, has=["never closed"])
    run("a missing table is a failure from SQLite", "SELECT * FROM nowhere", 1, has=["SQLite rejected the statement"])
    run("the time limit interrupts an endless query", "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) SELECT count(*) FROM c", 1,
        more=["--timeout", "0.5"], has=["stopped after the 0.5s time limit"])
    out = run("a table-valued pragma is denied by the read-only layer", "SELECT name FROM pragma_table_info('orders')", 1, has=["not authorized"])
    conn = sqlite3.connect(db)
    left = conn.execute("SELECT count(*) FROM orders").fetchone()[0]
    conn.close()
    expect("the database still holds 500 orders and the file is byte-identical", left == 500 and digest(db) == before, f"{left} rows")

    (folder / "q.sql").write_text("-- monthly paid total\nSELECT substr(created_at, 1, 7) AS month, round(sum(amount), 2) AS total\nFROM orders WHERE status = 'paid'\nGROUP BY 1 ORDER BY 1;\n", encoding="utf-8")
    case("--file and --log", script, ["--db", db, "--file", folder / "q.sql", "--log", folder / "runs.jsonl"], 0, has=["ROWS (12;", "logged to"])
    logged = json.loads((folder / "runs.jsonl").read_text(encoding="utf-8").splitlines()[0])
    expect("the log line holds the statement, a row count and a hash, and no rows", logged["rows"] == 12 and len(logged["result_hash"]) == 16 and "month" in logged["statement"] and len(logged) == 6)
    case("both --sql and --file: blocked", script, ["--db", db, "--sql", "SELECT 1", "--file", folder / "q.sql"], 2, has=["exactly one of"])
    case("no --db for SQLite: blocked", script, ["--sql", "SELECT 1"], 2, has=["--db <file> is needed"])
    case("a missing database file: blocked", script, ["--db", folder / "nope.sqlite", "--sql", "SELECT 1"], 2, has=["no such file"])
    case("a file that is not SQLite: blocked", script, ["--db", folder / "q.sql", "--sql", "SELECT 1"], 2, has=["not a SQLite database"])
    expect("the missing database was not created by the attempt", not (folder / "nope.sqlite").exists())

    case("postgres: checked and printed, never run", script, ["--dialect", "postgres", "--sql", "SELECT id FROM orders WHERE total > 10"], 2,
         has=["STATEMENT FOR YOUR OWN CLIENT (not run here)", "LIMIT 200", "connects to SQLite files only"])
    out = case("postgres: an existing LIMIT is kept", script, ["--dialect", "postgres", "--sql", "SELECT id FROM orders ORDER BY id LIMIT 7"], 2, has=["carries its own row limit"])
    expect("no second LIMIT was added", out.count("LIMIT") == 1, out)
    case("postgres: a write inside WITH is refused", script, ["--dialect", "postgres", "--sql", "WITH d AS (DELETE FROM t RETURNING *) SELECT * FROM d"], 1, has=["keyword DELETE"])
    case("postgres: SELECT INTO is refused", script, ["--dialect", "postgres", "--sql", "SELECT * INTO backup FROM orders"], 1, has=["keyword INTO"])
    case("mssql: told to add TOP", script, ["--dialect", "mssql", "--sql", "SELECT [order id] FROM orders"], 2, has=["add TOP 200"])


# ---------------------------------------------------------------- number-trace
def trace_cases(pack, folder):
    script = pack / "skills/number-trace/scripts/trace.py"
    rows = [[i, "refunded" if i <= 5 else ("paid" if i <= 35 else "new"), 25.5 if 5 < i <= 35 else 10] for i in range(1, 41)]
    write_csv(folder / "orders.csv", ["id", "status", "amount"], rows)
    conn = sqlite3.connect(folder / "shop.sqlite")
    conn.execute("CREATE TABLE orders (id INTEGER, status TEXT, amount REAL)")
    conn.executemany("INSERT INTO orders VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()
    (folder / "report.md").write_text(
        "# October report (2026)\n\n1. Orders: 40 in total, of which 30 were paid.\n2. Mean paid basket: 25.50\n3. Refund share: 12.5%\n\n"
        "The vendor survey score was 4.2.\nWe also had 7 complaints.\n\n| Measure | Value |\n|---|---|\n| Revenue | 9,999 |\n\n"
        "```\nSELECT 123 FROM nothing\n```\nSee `orders.csv` v2 for details, checked 2026-11-01 at 10:30.\n", encoding="utf-8")
    numbers = [
        {"value": "40", "label": "orders", "data": "orders.csv", "aggregate": "count"},
        {"value": "30", "label": "paid orders", "data": "shop.sqlite", "sql": "SELECT count(*) FROM orders WHERE status = 'paid'"},
        {"value": "25.50", "label": "mean paid basket", "data": "orders.csv", "aggregate": "mean", "column": "amount", "where": {"status": "paid"}},
        {"value": "12.5%", "label": "refund share", "data": "orders.csv", "aggregate": "share", "where": {"status": "refunded"}},
        {"value": "4.2", "label": "survey score", "note": "vendor PDF, page 3"},
        {"value": "9,999", "label": "revenue", "data": "orders.csv", "aggregate": "sum", "column": "amount"}]
    write_json(folder / "sources.json", {"ignore": ["2026"], "numbers": numbers})
    case("a wrong number, a number with no source, and one that cannot be re-run", script, [folder / "report.md", folder / "sources.json"], 1,
         has=["8 distinct numbers read from the report", "40 (line 3) 'orders': re-run gives 40", "30 (line 3) 'paid orders': re-run gives 30 (sql on shop.sqlite)",
              "25.50 (line 4) 'mean paid basket': re-run gives 25.5", "12.5% (line 5) 'refund share': re-run gives 12.5 (share on orders.csv",
              "[fail] 7 (line 8): no source", "[fail] 9,999 (line 12) 'revenue': does not match, re-run gives 865",
              "4.2 (line 7) 'survey score': has a source but was not re-run", "ignored as not data: 2026",
              "RESULT fail: 1 number(s) do not match and 1 have no source"],
         lacks=["123", "10:30"])

    (folder / "good.md").write_text("Orders: 40. Paid: 30. Mean paid basket 25.5, total 865.\n", encoding="utf-8")
    good = [dict(numbers[0]), dict(numbers[1]), dict(numbers[2], value="25.5"), dict(numbers[5], value="865")]
    write_json(folder / "good.json", {"numbers": good})
    case("every number traced and reproduced", script, [folder / "good.md", folder / "good.json"], 0, has=["FINDINGS (0)", "CHECKED AND FINE (4)"])
    write_json(folder / "manual.json", {"numbers": good[:3] + [{"value": "865", "label": "total", "note": "typed from the finance sheet"}]})
    case("a source that cannot be re-run: not verified", script, [folder / "good.md", folder / "manual.json"], 2, has=["has a source but was not re-run"])
    write_json(folder / "stale.json", {"numbers": good + [{"value": "77", "label": "old figure", "data": "orders.csv", "aggregate": "count"}]})
    case("a source entry that is not in the report is a warning", script, [folder / "good.md", folder / "stale.json"], 0, has=["'old figure' (77) does not appear in the report"])
    write_json(folder / "write.json", {"numbers": good[:3] + [{"value": "865", "label": "total", "data": "shop.sqlite", "sql": "DELETE FROM orders"}]})
    case("a source query that is not read-only is refused, not run", script, [folder / "good.md", folder / "write.json"], 2, has=["the query was refused"])
    conn = sqlite3.connect(folder / "shop.sqlite")
    expect("the refused query changed nothing", conn.execute("SELECT count(*) FROM orders").fetchone()[0] == 40)
    conn.close()
    write_json(folder / "gone.json", {"numbers": good[:3] + [{"value": "865", "label": "total", "data": "lost.csv", "aggregate": "sum", "column": "amount"}]})
    case("a missing data file: not verified", script, [folder / "good.md", folder / "gone.json"], 2, has=["data file not found: lost.csv"])
    (folder / "words.md").write_text("Nothing to count here.\n", encoding="utf-8")
    case("a report with no numbers fails", script, [folder / "words.md", folder / "good.json"], 1, has=["no numbers were read"])
    (folder / "broken.json").write_text("[", encoding="utf-8")
    case("a sources file that is not JSON: blocked", script, [folder / "good.md", folder / "broken.json"], 2, has=["not valid JSON"])
    case("a missing report: blocked", script, [folder / "nope.md", folder / "good.json"], 2, has=["cannot read the report"])


# ---------------------------------------------------------------- data-diff
def diff_cases(pack, folder):
    script = pack / "skills/data-diff/scripts/diff.py"
    old = [[1, "Asha", "IN", 10.5], [2, "Ben", "DE", 20], [3, "Chen", "US", 30], [4, "Dee", "IN", 40], [5, "Eli", "DE", 50]]
    write_csv(folder / "old.csv", ["id", "name", "country", "spend"], old)
    write_csv(folder / "new.csv", ["spend", "id", "country", "name", "tier"],
              [[50, 5, "DE", "Eli", "a"], [44, 4, "IN", "Dee", "b"], [30, 3, "CA", "Chen W", "a"], [10.5, 1, "IN", "Asha", "a"], [60, 6, "US", "Fay", "c"]])
    before = digest(folder / "old.csv"), digest(folder / "new.csv")
    case("added, removed and changed rows; reordered rows and columns", script, [folder / "old.csv", folder / "new.csv", "--key", "id"], 1,
         has=["ROWS  added 1, removed 1, changed 2, unchanged 2", "1 + 2 + 2 = 5 (old has 5)", "1 + 2 + 2 = 5 (new has 5)", "column(s) added: tier",
              "1 row(s) added: keys 6", "1 row(s) removed: keys 2", "per column: name 1, country 1, spend 1", "3: country: 'US' -> 'CA'",
              "the totals add up to both row counts", "row order differs", "RESULT fail: the versions differ: 1 added, 1 removed, 2 changed, 1 column(s) added, 0 removed"])
    case("--changes-ok lists the same differences and exits 0", script, [folder / "old.csv", folder / "new.csv", "--key", "id", "--changes-ok"], 0,
         has=["[warn] 2 row(s) changed", "FINDINGS (4)"])
    case("--ignore leaves a column out", script, [folder / "old.csv", folder / "new.csv", "--key", "id", "--ignore", "spend,name"], 1,
         has=["changed 1, unchanged 3", "column(s) left out by --ignore: name, spend"])
    expect("neither file was changed by the diff", before == (digest(folder / "old.csv"), digest(folder / "new.csv")))

    write_csv(folder / "shuffled.csv", ["name", "spend", "country", "id"], [[r[1], r[3], r[2], r[0]] for r in reversed(old)])
    case("the same data in another row and column order is no difference", script, [folder / "old.csv", folder / "shuffled.csv", "--key", "id"], 0,
         has=["all 5 rows match on 3 compared column(s)", "the order differs; columns were matched by name", "row order differs"])
    case("no key: blocked, with the candidates named", script, [folder / "old.csv", folder / "new.csv"], 2, has=["no key given", "id, name"])
    case("a key column that is missing: blocked", script, [folder / "old.csv", folder / "new.csv", "--key", "ref"], 2, has=["key column(s) not in both files: ref"])
    case("a key that repeats: blocked", script, [folder / "old.csv", folder / "new.csv", "--key", "country"], 2, has=["does not identify rows in the old file", "repeat a key"])
    case("a key of two columns", script, [folder / "old.csv", folder / "shuffled.csv", "--key", "country,name"], 0, has=["all 5 rows match"])

    conn = sqlite3.connect(folder / "old.sqlite")
    conn.execute("CREATE TABLE people (id INTEGER, name TEXT, country TEXT, spend REAL)")
    conn.executemany("INSERT INTO people VALUES (?, ?, ?, ?)", old)
    conn.commit()
    conn.close()
    case("CSV against SQLite: 20 and 20.0 differ as text", script, [folder / "old.csv", folder / "old.sqlite", "--key", "id"], 1, has=["changed 4, unchanged 1", "per column: spend 4"])
    case("CSV against SQLite with --loose: numbers compared by value", script, [folder / "old.csv", folder / "old.sqlite", "--key", "id", "--loose"], 0, has=["all 5 rows match"])
    case("--json writes the full diff", script, [folder / "old.csv", folder / "new.csv", "--key", "id", "--json", folder / "diff.json"], 1, has=["full diff written"])
    full = json.loads((folder / "diff.json").read_text(encoding="utf-8"))
    expect("the JSON diff holds 3 changed values, 1 added and 1 removed key", len(full["changes"]) == 3 and full["rows_added"] == [["6"]] and full["rows_removed"] == [["2"]])
    case("--json refuses to overwrite", script, [folder / "old.csv", folder / "new.csv", "--key", "id", "--json", folder / "diff.json"], 2, has=["already exists"])
    write_csv(folder / "codes_a.csv", ["code", "v"], [["007", 1], ["7", 2]])
    write_csv(folder / "codes_b.csv", ["code", "v"], [["7", 2], ["007", 1]])
    case("keys 007 and 7 stay two different rows", script, [folder / "codes_a.csv", folder / "codes_b.csv", "--key", "code"], 0, has=["all 2 rows match"])


# ---------------------------------------------------------------- data-clean
def clean_cases(pack, folder):
    script = pack / "skills/data-clean/scripts/clean.py"
    write_csv(folder / "messy.csv", ["id", "email", "signup", "country", "status"],
              [[1, " Ana@Example.com ", "03/04/2026", "UK", "paid"], [2, "bo@example.com", "2026-04-05", "U.K.", ""],
               [3, "CY@EXAMPLE.COM", "7 Apr 2026", "DE", "new"], [3, "CY@EXAMPLE.COM", "7 Apr 2026", "DE", "new"],
               [5, "di@example.com", "", "IN", "  "]])
    before = digest(folder / "messy.csv")
    plan = {"operations": [{"op": "trim", "columns": "*"}, {"op": "case", "columns": ["email"], "to": "lower"},
                           {"op": "parse_date", "columns": ["signup"], "formats": ["%d/%m/%Y", "%d %b %Y"]},
                           {"op": "map", "column": "country", "values": {"UK": "GB", "U.K.": "GB"}},
                           {"op": "fill", "column": "status", "value": "unknown"}, {"op": "drop_duplicates"}]}
    write_json(folder / "plan.json", plan)
    case("all six operations, with a log that replays exactly", script, [folder / "messy.csv", "--plan", folder / "plan.json", "--out", folder / "clean.csv"], 0,
         has=["1. trim on all columns: 2 change(s)", "2. case on email: 3 change(s)", "3. parse_date on signup: 3 change(s)", "4. map on country: 2 change(s)",
              "5. fill on status: 2 change(s)", "6. drop_duplicates on all columns: 1 change(s)", "replaying the 13 log line(s) on the input gives the output file exactly",
              "row count holds: 5 in = 4 out + 1 removed"])
    expect("the input file is byte-identical after cleaning", digest(folder / "messy.csv") == before)
    with open(folder / "clean.csv", encoding="utf-8", newline="") as handle:
        cleaned = list(csv.reader(handle))
    expect("the cleaned file holds the expected rows", cleaned[1] == ["1", "ana@example.com", "2026-04-03", "GB", "paid"] and cleaned[2][4] == "unknown" and cleaned[3][2] == "2026-04-07" and len(cleaned) == 5, str(cleaned))
    with open(folder / "clean.csv.changes.csv", encoding="utf-8", newline="") as handle:
        log = list(csv.reader(handle))
    expect("the change log has 13 lines with row, column, operation, before, after", len(log) == 14 and log[0] == ["row", "column", "operation", "before", "after"] and log[1] == ["1", "email", "trim", " Ana@Example.com ", "Ana@Example.com"])
    with open(folder / "clean.csv.removed.csv", encoding="utf-8", newline="") as handle:
        removed = list(csv.reader(handle))
    expect("the removed row is kept with its reason", len(removed) == 2 and removed[1][:2] == ["4", "exact duplicate of row 3"])
    case("an existing output is never overwritten", script, [folder / "messy.csv", "--plan", folder / "plan.json", "--out", folder / "clean.csv"], 2, has=["already exists"])
    case("the output may not be the input", script, [folder / "messy.csv", "--plan", folder / "plan.json", "--out", folder / "messy.csv"], 2, has=["already exists"])

    write_json(folder / "plan_fill.json", {"operations": [{"op": "fill", "column": "status"}]})
    case("fill with no stated value: blocked, nothing written", script, [folder / "messy.csv", "--plan", folder / "plan_fill.json", "--out", folder / "f.csv"], 2,
         has=["never picks a fill value"])
    expect("the refused fill wrote no file", not (folder / "f.csv").exists() and not (folder / "f.csv.changes.csv").exists())
    write_json(folder / "plan_dates.json", {"operations": [{"op": "parse_date", "columns": ["signup"], "formats": ["%d/%m/%Y", "%m/%d/%Y"]}]})
    case("a date two formats read differently is left alone and reported", script, [folder / "messy.csv", "--plan", folder / "plan_dates.json", "--out", folder / "d.csv"], 1,
         has=["row 1 signup (the stated formats read it as different days)", "row 3 signup (no stated format reads it)", "could not clean 3 value(s)"])
    with open(folder / "d.csv", encoding="utf-8", newline="") as handle:
        expect("the unreadable dates are unchanged in the output", list(csv.reader(handle))[1][2] == "03/04/2026")
    write_json(folder / "plan_noformat.json", {"operations": [{"op": "parse_date", "columns": ["signup"]}]})
    case("parse_date with no formats: blocked", script, [folder / "messy.csv", "--plan", folder / "plan_noformat.json", "--out", folder / "n.csv"], 2, has=["does not guess day and month order"])
    write_json(folder / "plan_op.json", {"operations": [{"op": "impute", "column": "status"}]})
    case("an unknown operation: blocked", script, [folder / "messy.csv", "--plan", folder / "plan_op.json", "--out", folder / "o.csv"], 2, has=["unknown operation 'impute'"])
    write_json(folder / "plan_col.json", {"operations": [{"op": "case", "columns": ["nope"], "to": "lower"}]})
    case("an unknown column: blocked", script, [folder / "messy.csv", "--plan", folder / "plan_col.json", "--out", folder / "c.csv"], 2, has=["not in the file: nope"])
    write_json(folder / "plan_trim.json", {"operations": [{"op": "trim", "columns": "*"}]})
    case("nothing to change is a pass", script, [folder / "clean.csv", "--plan", folder / "plan_trim.json", "--out", folder / "same.csv"], 0, has=["nothing needed changing", "replaying the 0 log line(s)"])
    (folder / "rows.jsonl").write_text('{"a": 1}\n', encoding="utf-8")
    case("a JSON-lines input: blocked", script, [folder / "rows.jsonl", "--plan", folder / "plan_trim.json", "--out", folder / "j.csv"], 2, has=["cleans CSV only"])
    (folder / "ragged.csv").write_text("a,b\n1,2\n3\n", encoding="utf-8")
    case("a ragged input: blocked", script, [folder / "ragged.csv", "--plan", folder / "plan_trim.json", "--out", folder / "r.csv"], 2, has=["wrong number of fields"])


# ---------------------------------------------------------------- stat-compare
def stat_cases(pack, folder):
    script = pack / "skills/stat-compare/scripts/compare.py"
    rng = random.Random(7)
    rows = [[f"u{i}", "control" if i % 2 else "new", round(rng.gauss(50 if i % 2 else 58, 10), 2)] for i in range(1, 121)]
    write_csv(folder / "ab.csv", ["user", "arm", "secs"], rows)
    base = [folder / "ab.csv", "--value", "secs", "--group", "arm"]
    first = case("a real difference, with units checked", script, base + ["--unit", "user"], 0,
                 has=["a = control, b = new", "n 60", "evidence of a difference", "independence: each user appears once and in one group", "Cohen's d", "95% bootstrap interval"])
    second = case("the same command again", script, base + ["--unit", "user"], 0)
    expect("two runs with the fixed seed print the same text", first == second)
    case("claim b-higher is supported", script, base + ["--unit", "user", "--claim", "b-higher"], 0, has=["claim 'new is higher than control' is supported"])
    case("claim a-higher is not supported", script, base + ["--unit", "user", "--claim", "a-higher"], 1, has=["claim 'control is higher than new' is not supported"])
    case("without --unit the independence line is in could not check", script, base, 2, has=["independence was not checked", "evidence of a difference"])

    same = [[f"u{i}", "a" if i % 2 else "b", round(rng.gauss(50, 10), 2)] for i in range(1, 121)]
    write_csv(folder / "same.csv", ["user", "arm", "secs"], same)
    case("no real difference: reported, not failed", script, [folder / "same.csv", "--value", "secs", "--group", "arm", "--unit", "user"], 0, has=["no evidence of a difference; this is not proof"])
    case("no real difference with --claim differ: fail", script, [folder / "same.csv", "--value", "secs", "--group", "arm", "--unit", "user", "--claim", "differ"], 1, has=["is not supported"])

    write_csv(folder / "tiny.csv", ["user", "arm", "secs"], [[f"u{i}", "a" if i % 2 else "b", 10 + i] for i in range(1, 9)])
    case("four values per group: not verified, no test run", script, [folder / "tiny.csv", "--value", "secs", "--group", "arm", "--unit", "user"], 2,
         has=["the smaller group has 4 value(s), under the minimum of 8", "RESULT OF THE COMPARISON: not verified, sample too small"], lacks=["p ="])
    write_csv(folder / "split.csv", ["user", "arm", "score"], [[f"u{i}", "low" if i <= 8 else "high", i] for i in range(1, 17)])
    case("complete separation, exact test: p = 2/12870", script, [folder / "split.csv", "--value", "score", "--group", "arm", "--unit", "user", "--a", "low", "--b", "high", "--permutations", "20000"], 0,
         has=["p = 0.0001554 (exact, all 12870 splits)", "difference in means (b - a): +8", "small sample"])
    repeated = [[f"u{i % 30}", "control" if (i % 30) % 2 else "new", row[2]] for i, row in enumerate(rows)]
    write_csv(folder / "repeated.csv", ["user", "arm", "secs"], repeated)
    case("units that repeat fail the independence check", script, [folder / "repeated.csv", "--value", "secs", "--group", "arm", "--unit", "user"], 1, has=["unit(s) appear more than once", "rows are not independent"])
    crossed = [list(r) for r in rows]
    crossed[1][0] = crossed[0][0]
    write_csv(folder / "crossed.csv", ["user", "arm", "secs"], crossed)
    case("a unit in both groups fails", script, [folder / "crossed.csv", "--value", "secs", "--group", "arm", "--unit", "user"], 1, has=["1 unit(s) appear in both groups"])

    skewed = [[f"u{i}", "a" if i % 2 else "b", round(rng.expovariate(1 / 20) ** 2 / 10 if i % 2 else rng.gauss(40, 2), 2)] for i in range(1, 121)]
    skewed[2][2] = "n/a"
    skewed[4][2] = ""
    write_csv(folder / "skewed.csv", ["user", "arm", "spend"], skewed)
    case("skew, unequal spread and unusable values are warned about", script, [folder / "skewed.csv", "--value", "spend", "--group", "arm", "--unit", "user"], 0,
         has=["heavy skew (a ", "unequal spread", "2 row(s) left out because spend is empty or not a number: rows 3, 5"])
    three = [[f"u{i}", ["x", "y", "z"][i % 3], i] for i in range(1, 61)]
    write_csv(folder / "three.csv", ["user", "arm", "v"], three)
    case("three groups and no --a/--b: blocked", script, [folder / "three.csv", "--value", "v", "--group", "arm"], 2, has=["holds 3 groups (x, y, z)"])
    case("three groups with --a and --b", script, [folder / "three.csv", "--value", "v", "--group", "arm", "--a", "x", "--b", "z", "--unit", "user"], 0, has=["a = x, b = z", "n 20"])
    case("an unknown column: blocked", script, [folder / "ab.csv", "--value", "nope", "--group", "arm"], 2, has=["column(s) not in the data: nope"])


# ---------------------------------------------------------------- chart-check
def chart_cases(pack, folder):
    script = pack / "skills/chart-check/scripts/chartcheck.py"
    write_csv(folder / "revenue.csv", ["month", "revenue_k", "orders"], [["Jan", 41, 300], ["Feb", 38, 280], ["Mar", 52, 350], ["Apr", 47, 320]])
    good = {"type": "bar", "title": "Revenue by month, 2026",
            "x": {"label": "Month", "categories": ["Jan", "Feb", "Mar", "Apr"], "ordered": True},
            "y": {"label": "Revenue", "unit": "EUR thousand", "min": 0, "max": 60},
            "series": [{"name": "2026", "values": [41, 38, 52, 47]}],
            "source": {"file": "revenue.csv", "category_column": "month", "series": {"2026": "revenue_k"}}}

    def spec(name, **changes):
        data = json.loads(json.dumps(good))
        for key, value in changes.items():
            if value is None:
                data.pop(key, None)
            elif isinstance(value, dict) and isinstance(data.get(key), dict):
                data[key].update(value)
            else:
                data[key] = value
        write_json(folder / name, data)
        return folder / name

    case("a correct bar chart", script, [spec("good.json")], 0, has=["FINDINGS (0)", "all 4 values match", "y axis of the bar chart includes zero"])
    case("a bar axis that starts at 30", script, [spec("truncated.json", y={"min": 30})], 1, has=["starts at 30, not 0", "the tallest bar looks 2.8 times the shortest, the real ratio is 1.4"])
    case("a value that differs from the source", script, [spec("wrong.json", series=[{"name": "2026", "values": [41, 38, 58, 47]}])], 1,
         has=["1 value(s) do not match: Mar: chart shows 58, source gives 52"])
    case("no source: not verified", script, [spec("nosource.json", source=None)], 2, has=["the spec names no source file"])
    case("a source file that is missing: not verified", script, [spec("lostsource.json", source={"file": "gone.csv"})], 2, has=["not compared with the source"])
    case("no axis labels and no unit", script, [spec("nolabels.json", x={"label": ""}, y={"label": None, "unit": ""})], 1, has=["axis label missing on: x, y", "no unit on the value axis: y"])
    case("no \"min\" on a bar axis: not verified", script, [spec("nomin.json", y={"min": None})], 2, has=["a truncated bar axis cannot be ruled out"])
    case("data above the axis maximum is cut off", script, [spec("clipped.json", y={"max": 50})], 1, has=["1 value(s) fall outside the y axis range"])
    case("months out of order", script, [spec("order.json", x={"categories": ["Feb", "Jan", "Mar", "Apr"]}, series=[{"name": "2026", "values": [38, 41, 52, 47]}])], 1,
         has=["natural order and are not in it"])
    case("a line chart may start above zero", script, [spec("line.json", type="line", y={"min": 30})], 0, has=["allowed for a line chart"])
    case("series length differs from the categories", script, [spec("short.json", series=[{"name": "2026", "values": [41, 38, 52]}])], 1, has=["do not all equal the 4 categories"])

    write_csv(folder / "teams.csv", ["team", "tickets"], [["Ops", 12], ["Web", 30], ["Data", 21], ["Apps", 17], ["QA", 9], ["Docs", 4], ["IT", 8]])
    teams = {"type": "bar", "title": "Open tickets by team", "x": {"label": "Team", "categories": ["Ops", "Web", "Data", "Apps", "QA", "Docs", "IT"], "ordered": False},
             "y": {"label": "Open tickets", "unit": "count", "min": 0}, "series": [{"name": "tickets", "values": [12, 30, 21, 17, 9, 4, 8]}],
             "source": {"file": "teams.csv", "category_column": "team"}}
    write_json(folder / "unsorted.json", teams)
    case("unordered bars not sorted by value: a warning", script, [folder / "unsorted.json"], 0, has=["not sorted by value", "all 7 values match"])
    write_json(folder / "pie.json", dict(teams, type="pie"))
    case("a pie with seven slices: a warning", script, [folder / "pie.json"], 0, has=["7 slices (limit 5)"])
    many = dict(teams, type="line", series=[{"name": f"s{i}", "values": [i] * 7} for i in range(8)], source=None)
    many.pop("source")
    many["y2"] = {"label": "Rate", "unit": "%"}
    many["series"][7]["axis"] = "y2"
    write_json(folder / "busy.json", many)
    case("eight series and two value axes: warnings, and no source", script, [folder / "busy.json"], 2, has=["8 series on one chart (limit 6)", "two value axes"])
    write_csv(folder / "raw.csv", ["month", "amount"], [["Jan", 10], ["Jan", 31], ["Feb", 38], ["Mar", 52], ["Apr", 47]])
    summed = dict(good, source={"file": "raw.csv", "category_column": "month", "series": {"2026": "amount"}, "aggregate": "sum"})
    write_json(folder / "summed.json", summed)
    case("values checked against a sum over raw rows", script, [folder / "summed.json"], 0, has=["(sum of amount): all 4 values match"])
    write_json(folder / "nosum.json", dict(summed, source=dict(summed["source"], aggregate="none")))
    case("several source rows and no aggregate stated", script, [folder / "nosum.json"], 1, has=["Jan: 2 source rows and no aggregate stated"])
    (folder / "broken.json").write_text("{", encoding="utf-8")
    case("a spec that is not JSON: blocked", script, [folder / "broken.json"], 2, has=["not valid JSON"])
    case("an unknown chart type: blocked", script, [spec("radar.json", type="radar")], 2, has=["one of bar, line, area, pie, scatter"])


# ---------------------------------------------------------------- sheet-audit
MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def make_xlsx(path, sheets, defined=(), extra=()):
    """sheets: list of (name, hidden, cells). cells maps "A1" to a number, a text, or a dict with any of
    f (formula), v (saved result), t ("e" for an error), shared (index), ref (range of a shared formula)."""
    strings = []

    def cell_xml(ref, value):
        if isinstance(value, dict):
            attributes = ' t="e"' if value.get("t") == "e" else (' t="str"' if isinstance(value.get("v"), str) and value.get("t") != "e" else "")
            if "shared" in value:
                formula = f'<f t="shared" si="{value["shared"]}"' + (f' ref="{value["ref"]}">{value["f"]}</f>' if "f" in value else "/>")
            else:
                formula = f"<f>{value['f']}</f>"
            saved = f"<v>{value['v']}</v>" if value.get("v") is not None else ""
            return f'<c r="{ref}"{attributes}>{formula}{saved}</c>'
        if isinstance(value, str):
            if value not in strings:
                strings.append(value)
            return f'<c r="{ref}" t="s"><v>{strings.index(value)}</v></c>'
        return f'<c r="{ref}"><v>{value}</v></c>'

    def row_of(ref):
        return int("".join(ch for ch in ref if ch.isdigit()))

    parts = {}
    for position, (name, hidden, cells) in enumerate(sheets, 1):
        rows = {}
        for ref in sorted(cells, key=lambda r: (row_of(r), len(r), r)):
            rows.setdefault(row_of(ref), []).append(cell_xml(ref, cells[ref]))
        body = "".join(f'<row r="{number}">{"".join(items)}</row>' for number, items in sorted(rows.items()))
        parts[f"xl/worksheets/sheet{position}.xml"] = f'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="{MAIN}"><sheetData>{body}</sheetData></worksheet>'
    names = "".join(f'<definedName name="{n}">{target}</definedName>' for n, target in defined)
    parts["xl/workbook.xml"] = (f'<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="{MAIN}" xmlns:r="{REL}"><sheets>'
                                + "".join(f'<sheet name="{name}" sheetId="{i}" r:id="rId{i}"{" state=" + chr(34) + "hidden" + chr(34) if hidden else ""}/>' for i, (name, hidden, _) in enumerate(sheets, 1))
                                + "</sheets>" + (f"<definedNames>{names}</definedNames>" if names else "") + "</workbook>")
    parts["xl/_rels/workbook.xml.rels"] = ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                                           + "".join(f'<Relationship Id="rId{i}" Type="{REL}/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets) + 1))
                                           + "</Relationships>")
    parts["xl/sharedStrings.xml"] = f'<?xml version="1.0" encoding="UTF-8"?><sst xmlns="{MAIN}">' + "".join(f"<si><t>{s}</t></si>" for s in strings) + "</sst>"
    parts["_rels/.rels"] = ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                            f'<Relationship Id="rId1" Type="{REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    parts["[Content_Types].xml"] = ('<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                                    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/></Types>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in parts.items():
            archive.writestr(name, text)
        for name in extra:
            archive.writestr(name, "<x/>")


def sheet_cases(pack, folder):
    script = pack / "skills/sheet-audit/scripts/audit.py"
    budget = {"A1": "item", "B1": "qty", "C1": "price", "D1": "cost", "E1": "rate"}
    for row in range(2, 8):
        budget.update({f"A{row}": f"item {row}", f"B{row}": row, f"C{row}": 2.5, f"D{row}": {"f": f"B{row}*C{row}", "v": row * 2.5}})
    budget.update({"A8": "total", "B8": {"f": "SUM(B2:B7)", "v": 27}, "D8": {"f": "SUM(D2:D7)", "v": 67.5}, "E2": 1})
    make_xlsx(folder / "good.xlsx", [("Budget", False, budget)])
    before = digest(folder / "good.xlsx")
    case("a sound workbook", script, [folder / "good.xlsx"], 0, has=["FINDINGS (0)", "read 33 cells, 8 formulas", "'Budget': no error cells (8 formulas read)"])
    expect("the workbook is byte-identical after the audit", digest(folder / "good.xlsx") == before)

    bad = dict(budget)
    bad["D4"] = 99
    bad["D6"] = {"f": "B6*C6*1.18", "v": 17.7}
    bad["E3"] = {"f": "B3/0", "v": "#DIV/0!", "t": "e"}
    bad["E4"] = {"f": "[1]Rates!$A$1*B4", "v": 4}
    bad["E5"] = {"f": "Z99+B5", "v": 5}
    bad["E6"] = {"f": "Notes!A1+Notes!B9", "v": 3}
    make_xlsx(folder / "bad.xlsx", [("Budget", False, bad), ("Notes", True, {"A1": 3})])
    case("errors, a typed number, a broken pattern, empty and outside references, a hidden sheet", script, [folder / "bad.xlsx"], 1,
         has=["1 error cell(s): Budget!E3 #DIV/0!", "1 number(s) typed where a formula is expected: Budget!D4 = 99 (formulas on both sides in its column)",
              "1 formula(s) differ from the same formula on both sides: Budget!D6 =B6*C6*1.18", "1 formula(s) on 'Budget' read from another workbook: Budget!E4",
              "2 reference(s) on 'Budget' point at empty cells: Budget!E5 -> Z99, Budget!E6 -> Notes!B9", "1 formula(s) on 'Budget' hold a typed number: Budget!D6 (1.18)",
              "sheet 'Notes' is hidden"])
    case("--sheet limits the audit", script, [folder / "bad.xlsx", "--sheet", "Notes"], 0, has=["sheet 'Notes' is hidden", "'Notes': 1 cells and no formulas"], lacks=["error cell"])
    case("--sheet with an unknown name: blocked", script, [folder / "bad.xlsx", "--sheet", "Nope"], 2, has=["no sheet named 'Nope'"])

    shared = {"A1": "qty", "B1": "price", "C1": "cost"}
    for row in range(2, 8):
        shared.update({f"A{row}": row, f"B{row}": 3, f"C{row}": {"shared": 0, "v": row * 3}})
    shared["C2"] = {"shared": 0, "ref": "C2:C7", "f": "A2*B2", "v": 6}
    shared["C5"] = 15
    make_xlsx(folder / "shared.xlsx", [("Calc", False, shared)])
    case("a number typed into a run of shared formulas", script, [folder / "shared.xlsx"], 1, has=["Calc!C5 = 15 (formulas on both sides in its column)"])
    across = {"A1": "q1", "B1": "q2", "C1": "q3", "D1": "q4", "A2": 5, "B2": 6, "C2": 7, "D2": 8, "A3": 2, "B3": 2, "C3": 2, "D3": 2,
              "A4": {"f": "A2*A3", "v": 10}, "B4": {"f": "B2*B3", "v": 12}, "C4": {"f": "C2+C3", "v": 9}, "D4": {"f": "D2*D3", "v": 16},
              "E4": {"f": "SUM($A$4:D4)", "v": 47}}
    make_xlsx(folder / "across.xlsx", [("Row", False, across)])
    case("a formula that breaks its row: a warning", script, [folder / "across.xlsx"], 0, has=["1 formula(s) differ from the same formula on both sides: Row!C4 =C2+C3 (its row neighbours hold =B2*B3)"])

    unsaved = dict(budget)
    unsaved["D8"] = {"f": "SUM(D2:D7)"}
    make_xlsx(folder / "unsaved.xlsx", [("Budget", False, unsaved)])
    case("a formula with no saved result: not verified", script, [folder / "unsaved.xlsx"], 2, has=["1 formula(s) on 'Budget' have no saved result", "Budget!D8"])
    named = dict(budget)
    named["E3"] = {"f": "SUM(Sales[Amount])+SUM(B:B)", "v": 1}
    make_xlsx(folder / "features.xlsx", [("Budget", False, named)], defined=[("TaxRate", "Budget!$E$2"), ("_xlnm.Print_Area", "Budget!$A$1:$E$8")],
              extra=["xl/vbaProject.bin", "xl/pivotTables/pivotTable1.xml", "xl/externalLinks/externalLink1.xml"])
    case("macros, a pivot table, links, a named range, table and whole-column references: not verified", script, [folder / "features.xlsx"], 2,
         has=["holds macros", "1 pivot table(s) were not read", "links to other files", "1 named range(s) are defined", "1 formula(s) use table references", "1 formula(s) use whole-column"])

    (folder / "old.xls").write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64)
    case("an old binary .xls: blocked", script, [folder / "old.xls"], 2, has=["old binary workbook"])
    (folder / "table.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    case("a CSV: blocked", script, [folder / "table.csv"], 2, has=["not an .xlsx file"])
    with zipfile.ZipFile(folder / "other.zip", "w") as archive:
        archive.writestr("readme.txt", "hello")
    case("a zip that is not a workbook: blocked", script, [folder / "other.zip"], 2, has=["xl/workbook.xml is missing"])
    case("a missing file: blocked", script, [folder / "nope.xlsx"], 2, has=["cannot read"])


# ---------------------------------------------------------------- notebook-check
def notebook(cells):
    out = []
    for cell in cells:
        if cell[0] == "md":
            out.append({"cell_type": "markdown", "metadata": {}, "source": cell[1]})
        else:
            source, count = cell[1], cell[2]
            outputs = cell[3] if len(cell) > 3 else []
            out.append({"cell_type": "code", "metadata": {}, "execution_count": count, "source": source.splitlines(keepends=True), "outputs": outputs})
    return {"cells": out, "metadata": {"kernelspec": {"name": "python3", "language": "python", "display_name": "Python 3"}}, "nbformat": 4, "nbformat_minor": 5}


def notebook_cases(pack, folder):
    script = pack / "skills/notebook-check/scripts/nbcheck.py"
    no_jupyter = dict(os.environ, PATH=str(folder / "empty-bin"))
    (folder / "empty-bin").mkdir()
    run = lambda label, name, want, **kw: case(label, script, [folder / name] + kw.pop("more", []), want, env=kw.pop("env", no_jupyter), cwd=folder, **kw)

    tidy = notebook([("md", "# Sales"), ("code", "%matplotlib inline\nimport csv\nrows = [1, 2, 3]", 1),
                     ("code", "def total(values):\n    return sum(values) * scale\n\nscale = 2", 2),
                     ("code", "!echo listing\nprint(total(rows))", 3, [{"output_type": "stream", "name": "stdout", "text": ["12\n"]}]),
                     ("code", "%%bash\nls | head -3", 4)])
    write_json(folder / "tidy.ipynb", tidy)
    before = digest(folder / "tidy.ipynb")
    run("a tidy notebook without Jupyter: file checks fine, re-run not verified", "tidy.ipynb", 2,
        has=["FINDINGS (0)", "every code cell ran once, top to bottom (counts 1 to 4)", "no saved output holds an error", "name scan: every name used",
             "not re-run: `jupyter nbconvert` was not found"])
    run("--run without Jupyter is still not verified, and runs nothing", "tidy.ipynb", 2, more=["--run"], has=["was not found on this machine"])
    expect("no output folder was made when Jupyter is absent", not (folder / ".mstack").exists())

    secret = "sk" + "-" + "a1B2c3D4e5F6g7H8i9J0k1L2"
    home = "/Us" + "ers/priya/data/sales.csv"
    messy = notebook([("code", "import csv\nprint(len(df))", 3, [{"output_type": "error", "ename": "NameError", "evalue": "name 'df' is not defined", "traceback": []}]),
                      ("code", f"df = list(csv.reader(open('{home}')))", 1),
                      ("code", "api_" + f"key = '{secret}'\nprint(undefined_thing)", None),
                      ("code", "total = 0\nfor row in df:\n    total += 1", 7, [{"output_type": "stream", "name": "stdout", "text": "token: " + secret + "\n"}])])
    write_json(folder / "messy.ipynb", messy)
    run("out of order, an error output, hidden state, a machine path and a credential", "messy.ipynb", 1,
        has=["cells were run out of order: cell 2 [1] ran before cell 1 [3]", "1 code cell(s) were never run: cells 3", "cell 1: NameError: name 'df' is not defined",
             "cell 1 uses `df`, first defined in cell 2", "cell 3 uses `undefined_thing`", "/Users/<name>...", "look like a credential (values not shown)",
             "cell 3: looks like a value assigned to a name such as password, token or api_key", "output of cell 4: looks like a provider token"],
        lacks=[secret, "priya"])

    cleared = notebook([("code", "x = 1", None), ("code", "print(x)", None)])
    write_json(folder / "cleared.ipynb", cleared)
    run("outputs cleared: run order cannot be read", "cleared.ipynb", 2, has=["no cell carries an execution count"])
    gaps = notebook([("code", "x = 1", 4), ("code", "y = x + 1", 9), ("code", "print(y)", 12)])
    write_json(folder / "gaps.ipynb", gaps)
    run("counts in order but with gaps: a warning", "gaps.ipynb", 2, has=["execution counts are in order but do not run 1, 2, 3 (they are 4, 9, 12)"])
    broken_cell = notebook([("code", "x = (1,", 1), ("code", "from math import *\nprint(sqrt(x))", 2)])
    write_json(folder / "syntax.ipynb", broken_cell)
    run("a cell that does not parse, and a star import", "syntax.ipynb", 2, has=["1 cell(s) do not parse as Python", "from ... import *"])
    (folder / "notjson.ipynb").write_text("# %% not a notebook\nx = 1\n", encoding="utf-8")
    run("a file that is not JSON: blocked", "notjson.ipynb", 2, has=["is not valid JSON"])
    write_json(folder / "v3.ipynb", {"nbformat": 3, "worksheets": [{"cells": []}]})
    run("an old-format notebook: blocked", "v3.ipynb", 2, has=["has no 'cells' list"])
    write_json(folder / "empty.ipynb", notebook([("md", "# only words")]))
    run("a notebook with no code fails", "empty.ipynb", 1, has=["no code cells with content"])

    # The re-run plumbing, against a stub named jupyter. This proves the command line and the reading of the copy, not Jupyter itself.
    stub_dir = folder / "stub-bin"
    stub_dir.mkdir()
    stub = stub_dir / "jupyter"
    stub.write_text("#!" + sys.executable + "\nimport os, shutil, sys\nargs = sys.argv[1:]\n"
                    "if args[:2] == ['nbconvert', '--version']:\n    print('0.0-stub'); sys.exit(0)\n"
                    "if os.environ.get('STUB_FAIL'):\n    sys.stderr.write('CellExecutionError: boom in cell 2\\n'); sys.exit(1)\n"
                    "shutil.copyfile(args[-1], os.path.join(args[args.index('--output-dir') + 1], args[args.index('--output') + 1]))\n", encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    with_stub = dict(os.environ, PATH=str(stub_dir) + os.pathsep + os.environ.get("PATH", ""))
    run("stub jupyter present, no --run: asks before running", "tidy.ipynb", 2, env=with_stub, has=["Jupyter is installed, but --run was not given"])
    run("stub jupyter, --run: the copy is read back", "tidy.ipynb", 0, env=with_stub, more=["--run", "--out-dir", folder / "rerun"],
        has=["re-run: all 4 code cells ran top to bottom", "re-run: text outputs match the saved ones"])
    expect("the copy exists and the notebook is byte-identical", (folder / "rerun" / "tidy.rerun.ipynb").exists() and digest(folder / "tidy.ipynb") == before)
    run("stub jupyter, --run again: an existing copy is not overwritten", "tidy.ipynb", 2, env=with_stub, more=["--run", "--out-dir", folder / "rerun"], has=["already exists"])
    run("stub jupyter that fails: the re-run is a failure", "tidy.ipynb", 1, env=dict(with_stub, STUB_FAIL="1"), more=["--run", "--out-dir", folder / "rerun2"],
        has=["the re-run stopped: a cell failed in a fresh kernel", "boom in cell 2"])


# ---------------------------------------------------------------- query-review
def review_cases(pack, folder):
    script = pack / "skills/query-review/scripts/review.py"
    db = folder / "shop.sqlite"
    make_shop(db, orders=20000)
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE notes (id INTEGER, tag TEXT)")
    conn.execute("CREATE TABLE tags (tag TEXT, colour TEXT)")
    conn.executemany("INSERT INTO notes VALUES (?, ?)", [(i, f"t{i % 300}") for i in range(3000)])
    conn.executemany("INSERT INTO tags VALUES (?, ?)", [(f"t{i}", "red") for i in range(3000)])
    conn.commit()
    conn.close()
    before = digest(db)
    run = lambda label, sql, want, **kw: case(label, script, ["--sql", sql] + kw.pop("more", ["--db", db]), want, **kw)
    run("an indexed lookup with named columns and a limit", "SELECT id, amount FROM orders WHERE customer_id = 7 LIMIT 20", 0,
        has=["FINDINGS (0)", "index used: SEARCH orders USING INDEX idx_orders_customer", "QUERY PLAN"])
    run("SELECT * with a filter no index serves, and no limit", "SELECT * FROM orders WHERE status = 'paid'", 1,
        has=["SELECT * returns every column", "full scan of orders (20000 rows, large-table line 10000); no index serves the filter", "no LIMIT on an exploratory query"])
    run("the same scan is fine when the table is under the line", "SELECT id FROM orders WHERE status = 'paid' LIMIT 5", 0, more=["--db", db, "--large-rows", "50000"],
        has=["scan of orders is small (20000 rows, large-table line 50000)"])
    run("an alias is traced back to its table", "SELECT o.id FROM orders AS o WHERE o.status = 'new' LIMIT 3", 1, has=["full scan of orders (20000 rows"])
    run("a JOIN with no ON", "SELECT o.id, c.name FROM orders o JOIN customers c LIMIT 5", 1, has=["JOIN with customers has no ON or USING"])
    run("a comma join with no WHERE", "SELECT o.id, c.name FROM orders o, customers c LIMIT 5", 1, has=["tables joined with a comma and no WHERE (orders, customers)"])
    run("a comma join that is linked in WHERE", "SELECT o.id, c.name FROM orders o, customers c WHERE o.customer_id = c.id AND c.id = 3 LIMIT 5", 0,
        has=["comma join (orders, customers) is linked in WHERE"])
    run("a filter wrapped in a function", "SELECT id FROM orders WHERE date(created_at) = '2026-03-01' LIMIT 5", 1,
        has=["filter wraps created_at in date()", "full scan of orders"])
    run("an aggregate needs no limit; a small scan is fine", "SELECT count(*) FROM customers", 0, has=["no row limit needed", "scan of customers is small (50 rows"])
    run("NOT IN with a subquery and a leading wildcard", "SELECT name FROM customers WHERE name LIKE '%7' AND id NOT IN (SELECT customer_id FROM orders) LIMIT 5", 0,
        has=["LIKE with a leading %", "NOT IN with a subquery"])
    run("a join that makes SQLite build an index on every run", "SELECT n.id, t.colour FROM notes n JOIN tags t ON n.tag = t.tag LIMIT 10", 0,
        has=["builds a temporary index on tags every time this runs", "a permanent index is missing"])
    run("a CROSS JOIN is named, not failed", "SELECT c.id, t.tag FROM customers c CROSS JOIN tags t LIMIT 5", 0, has=["CROSS JOIN with t"])
    run("a join inside a subquery with its own WHERE keeps its ON", "SELECT c.name FROM customers c JOIN (SELECT customer_id FROM orders WHERE amount > 190) big ON big.customer_id = c.id LIMIT 5", 1,
        has=["1 JOIN(s), each with a condition", "full scan of orders"], lacks=["has no ON or USING"])
    run("--purpose production accepts no limit", "SELECT id, amount FROM orders WHERE customer_id = 7", 0, more=["--db", db, "--purpose", "production"],
        has=["accepted because --purpose production was given"])
    expect("the database is byte-identical after the reviews", digest(db) == before)

    run("no database: text checks only, not verified", "SELECT * FROM orders o JOIN customers c ON c.id = o.customer_id", 2, more=[],
        has=["SELECT * returns every column", "the query plan was not read: no SQLite file was given"])
    run("postgres: text checks only, not verified", "SELECT id FROM orders WHERE lower(status) = 'paid'", 2, more=["--dialect", "postgres"],
        has=["filter wraps status in lower()", "does not connect to postgres"])
    run("a text finding that blocks needs no plan", "SELECT a.x FROM a JOIN b", 1, more=["--dialect", "mysql"], has=["JOIN with b has no ON or USING"])
    run("a statement that is not a SELECT: blocked", "UPDATE orders SET amount = 0", 2, has=["reviews one SELECT or WITH statement"])
    run("a table that does not exist: the plan is not read", "SELECT id FROM nowhere LIMIT 1", 2, has=["the query plan was not read: SQLite rejected the statement"])
    case("a file that is not SQLite: blocked", script, ["--sql", "SELECT 1", "--db", folder / "nope.sqlite"], 2, has=["not a readable SQLite database"])
    (folder / "q.sql").write_text("-- who spends most\nSELECT customer_id, sum(amount) AS spend\nFROM orders\nGROUP BY customer_id\nORDER BY spend DESC\nLIMIT 10;\n", encoding="utf-8")
    case("--file: a grouped query reads the whole index (a warning)", script, ["--file", folder / "q.sql", "--db", db], 0, has=["reads the whole index of orders (20000 rows"])


SKILLS = {"data-profile": profile_cases, "data-check": check_cases, "sql-run": sql_cases, "number-trace": trace_cases, "data-diff": diff_cases,
          "data-clean": clean_cases, "stat-compare": stat_cases, "chart-check": chart_cases, "sheet-audit": sheet_cases,
          "notebook-check": notebook_cases, "query-review": review_cases}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pack", type=pathlib.Path, help="path to packs/data")
    parser.add_argument("parent", type=pathlib.Path, help="folder in which data-<skill>/ folders are made, for example .testrun")
    parser.add_argument("--only", choices=sorted(SKILLS), help="run the cases of one skill")
    args = parser.parse_args()
    pack, parent = args.pack.resolve(), args.parent.resolve()
    chosen = [args.only] if args.only else list(SKILLS)
    existing = [name for name in chosen if (parent / f"data-{name.replace('data-', '') if name.startswith('data-') else name}").exists()]
    if existing:
        sys.exit(f"refusing: fixture folder(s) already exist under {parent} for: {', '.join(existing)}")
    for name in chosen:
        folder = parent / f"data-{name.replace('data-', '') if name.startswith('data-') else name}"
        folder.mkdir(parents=True)
        print(f"#### {name}  ({folder})")
        start = dict(RESULTS)
        SKILLS[name](pack, folder)
        print(f"     {name}: {RESULTS['run'] - start['run']} checks, {RESULTS['wrong'] - start['wrong']} wrong")
    print(f"data cases: {RESULTS['run']} run, {RESULTS['wrong']} wrong")
    sys.exit(1 if RESULTS["wrong"] else 0)


if __name__ == "__main__":
    main()

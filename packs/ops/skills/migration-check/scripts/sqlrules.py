#!/usr/bin/env python3
"""Read SQL migration files and flag statements that lock a table, lose data or leave no way back.

  sqlrules.py PATH [PATH ...] [--code DIR] [--forward-only] [--engine postgres|mysql|sqlite|other] [--json]

PATH is a .sql file or a folder of them. Give only the migrations that are still to be applied.
Files named *.down.sql, down.sql, *.undo.sql or U<n>__*.sql, and the part of a file after a "-- down" style
marker, are treated as the way back and are not linted.

Rules (BLOCK fails the check, WARN does not):
  drop-table, drop-column, truncate, delete-all     BLOCK  data is gone once this runs
  type-change                                       BLOCK  rewrites the table under a lock, or loses precision
  rename                                            BLOCK  code that still uses the old name breaks at once
  not-null-no-default                               BLOCK  fails on a table that has rows
  index-blocks-writes, concurrent-in-transaction    BLOCK  PostgreSQL lock rules
  no-way-back                                       BLOCK  no down migration found (accept with --forward-only)
  set-not-null, constraint-validates, update-all, schema-and-data   WARN

--code DIR looks for the old name of every dropped or renamed table and column in source files under DIR.
The script reads text only. It connects to no database and applies nothing; say so when you report.

Exit codes: 0 = no BLOCK finding, 1 = at least one, 2 = not verified or blocked (no SQL found, or lock rules
skipped because the engine is not PostgreSQL).
"""
import argparse
import json
import os
import pathlib
import re
import sys

IDENT = r'("[^"]+"|`[^`]+`|\[[^\]]+\]|[\w.]+)'
DOWN_MARK = re.compile(r"^\s*--\s*(\+goose\s+down|\+migrate\s+down|migrate:down|@?down\b|rollback\b|undo\b)", re.I)
NOT_COLUMN = r"(?!CONSTRAINT\b|PRIMARY\b|FOREIGN\b|UNIQUE\b|CHECK\b|INDEX\b|KEY\b|PARTITION\b|EXCLUDE\b)"
NOT_DROPPED_COLUMN = r"(?!COLUMN\b|CONSTRAINT\b|DEFAULT\b|NOT\b|INDEX\b|PRIMARY\b|FOREIGN\b|KEY\b|EXPRESSION\b|IDENTITY\b|PARTITION\b)"
SOURCE = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte", ".py", ".rs", ".go", ".rb", ".java", ".kt", ".php", ".cs"}
SKIP = {"node_modules", ".git", "dist", "build", "target", ".next", ".venv", "venv", "__pycache__", ".mstack", "vendor", "migrations", "migrate"}
POSTGRES_ONLY = {"index-blocks-writes", "concurrent-in-transaction", "set-not-null", "constraint-validates"}
RULES = {
    "drop-table": ("BLOCK", "the table and every row in it are removed", "keep the table until a restore of a backup was proven (restore-test), and drop it in a later migration"),
    "drop-column": ("BLOCK", "the column's data is removed and cannot be brought back by a down migration", "stop reading and writing the column in code first, deploy that, then drop it in a later migration"),
    "truncate": ("BLOCK", "every row in the table is removed", "if this is meant, say so to the user and prove a backup can be restored first"),
    "delete-all": ("BLOCK", "DELETE without WHERE removes every row", "add the WHERE clause, or confirm with the user that the whole table is meant"),
    "type-change": ("BLOCK", "changing a column's type rewrites the table under a lock that stops reads and writes, and a narrower type loses data", "add a new column, copy in batches, switch the code, then drop the old column"),
    "rename": ("BLOCK", "code that is running with the old name fails as soon as this applies, before the new code is live", "add the new name, write to both, move the readers, then remove the old name in a later migration"),
    "not-null-no-default": ("BLOCK", "adding a required column with no default fails when the table already has rows", "add it with a default, or add it nullable, fill it, then set NOT NULL"),
    "index-blocks-writes": ("BLOCK", "a plain CREATE INDEX stops writes to the table until the index is built", "use CREATE INDEX CONCURRENTLY, outside a transaction"),
    "concurrent-in-transaction": ("BLOCK", "CREATE INDEX CONCURRENTLY cannot run inside a transaction block; the migration will fail", "put it in its own migration with no BEGIN, and switch off the tool's wrapping transaction for that file"),
    "no-way-back": ("BLOCK", "no down migration was found for this file", "write the down step, or state that the project is forward-only and run again with --forward-only"),
    "set-not-null": ("WARN", "SET NOT NULL reads the whole table while holding a lock", "on a large table add a NOT VALID check constraint first, validate it, then set NOT NULL"),
    "constraint-validates": ("WARN", "adding a foreign key or check constraint validates every row while holding a lock", "add it NOT VALID, then VALIDATE CONSTRAINT in a separate step"),
    "update-all": ("WARN", "UPDATE without WHERE rewrites every row in one transaction", "update in batches, apart from schema changes"),
    "schema-and-data": ("WARN", "the file changes the schema and the data together, so one long transaction holds the schema lock", "put data changes in their own migration"),
}


def statements(text):
    """Split SQL into (line, statement) pairs. Comments are dropped and the inside of quoted strings is blanked."""
    out, buf, line, start, i, n = [], [], 1, None, 0, len(text)
    while i < n:
        ch, two = text[i], text[i:i + 2]
        if two == "--":
            end = text.find("\n", i)
            i = n if end == -1 else end
            continue
        if two == "/*":
            end = text.find("*/", i + 2)
            end = n if end == -1 else end + 2
            line += text.count("\n", i, end)
            i = end
            continue
        dollar = re.match(r"\$[A-Za-z_]*\$", text[i:]) if ch == "$" else None
        if ch == "'" or dollar:
            close = dollar.group(0) if dollar else "'"
            end = text.find(close, i + len(close))
            while not dollar and end != -1 and text[end:end + 2] == "''":
                end = text.find("'", end + 2)
            end = n if end == -1 else end + len(close)
            start = start or line
            line += text.count("\n", i, end)
            buf.append("''")
            i = end
            continue
        if ch == ";":
            body = " ".join("".join(buf).split())
            if body:
                out.append((start or line, body))
            buf, start = [], None
        else:
            if not ch.isspace() and start is None:
                start = line
            buf.append(ch)
        if ch == "\n":
            line += 1
        i += 1
    body = " ".join("".join(buf).split())
    if body:
        out.append((start or line, body))
    return out


def clean(name):
    return name.strip('"`[]').split(".")[-1].lower()


def top_level_parts(text):
    parts, depth, last = [], 0, 0
    for i, ch in enumerate(text):
        depth += ch == "("
        depth -= ch == ")"
        if ch == "," and depth == 0:
            parts.append(text[last:i])
            last = i + 1
    return parts + [text[last:]]


def is_down_file(path):
    name = path.name.lower()
    return name == "down.sql" or name.endswith((".down.sql", ".undo.sql", "_down.sql")) or bool(re.match(r"u\d[\w.]*__", name))


def has_sibling_down(path):
    name, folder = path.name, path.parent
    options = [name[:-7] + ".down.sql" if name.lower().endswith(".up.sql") else None,
               "down.sql" if name.lower() == "up.sql" else None,
               path.stem + ".down.sql", path.stem + ".undo.sql", path.stem + "_down.sql",
               "U" + name[1:] if re.match(r"V\d", name) else None]
    return any(o and (folder / o).is_file() for o in options)


def lint_file(path, created, engine):
    """Return (findings, old names). A finding is (rule, line, statement, detail)."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    lines = raw.splitlines()
    mark = next((i for i, l in enumerate(lines) if DOWN_MARK.match(l)), None)
    up_text = "\n".join(lines[:mark]) if mark is not None else raw
    down_inside = mark is not None and bool(statements("\n".join(lines[mark:])))
    found, old_names = [], []
    stmts = statements(up_text)
    in_tx = False
    kinds = set()
    for line, sql in stmts:
        up = sql.upper()

        def add(rule, detail=""):
            found.append((rule, line, sql, detail))
        if re.match(r"(BEGIN|START\s+TRANSACTION)\b", up):
            in_tx = True
        elif re.match(r"(COMMIT|END|ROLLBACK)\b", up):
            in_tx = False
        table = re.match(r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?" + IDENT, sql, re.I)
        table_name = clean(table.group(1)) if table else None
        if re.match(r"(CREATE|ALTER|DROP)\b", up):
            kinds.add("schema")
        if re.match(r"(UPDATE|DELETE|INSERT)\b", up):
            kinds.add("data")
        m = re.match(r"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?" + IDENT, sql, re.I)
        if m:
            add("drop-table")
            old_names.append(clean(m.group(1)))
        if re.match(r"TRUNCATE\b", up):
            add("truncate")
        if re.match(r"DELETE\s+FROM\b", up) and " WHERE " not in up + " ":
            add("delete-all")
        if re.match(r"UPDATE\b", up) and " WHERE " not in up + " ":
            add("update-all")
        m = re.match(r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(CONCURRENTLY\s+)?.*?\bON\s+(?:ONLY\s+)?" + IDENT, sql, re.I)
        if m and clean(m.group(2)) not in created:
            if m.group(1) and in_tx:
                add("concurrent-in-transaction")
            elif not m.group(1):
                add("index-blocks-writes", f"table {clean(m.group(2))}")
        if re.match(r"(ALTER\s+TABLE\s+\S+\s+)?RENAME\s+TABLE\b", up):
            add("rename")
        if table:
            actions = top_level_parts(sql[table.end():])
            for action in actions:
                act = action.strip()
                au = act.upper()
                m = re.match(r"DROP\s+COLUMN\s+(?:IF\s+EXISTS\s+)?" + IDENT, act, re.I) or re.match(r"DROP\s+" + NOT_DROPPED_COLUMN + IDENT, act, re.I)
                if m:
                    add("drop-column", f"{table_name}.{clean(m.group(1))}")
                    old_names.append(clean(m.group(1)))
                m = re.match(r"RENAME\s+(?:COLUMN\s+)?" + IDENT + r"\s+TO\s+" + IDENT, act, re.I)
                if m:
                    add("rename", f"{table_name}.{clean(m.group(1))} to {clean(m.group(2))}")
                    old_names.append(clean(m.group(1)))
                elif re.match(r"RENAME\s+TO\s+", au):
                    add("rename", f"table {table_name}")
                    old_names.append(table_name)
                if re.match(r"ALTER\s+(COLUMN\s+)?\S+\s+(SET\s+DATA\s+)?TYPE\b", au) or re.match(r"(MODIFY|CHANGE)\s+(COLUMN\s+)?\S+", au):
                    add("type-change", table_name)
                if re.match(r"ALTER\s+(COLUMN\s+)?\S+\s+SET\s+NOT\s+NULL\b", au) and table_name not in created:
                    add("set-not-null", table_name)
                if re.match(r"ADD\s+(CONSTRAINT\s+\S+\s+)?(FOREIGN\s+KEY|CHECK)\b", au) and "NOT VALID" not in au and table_name not in created:
                    add("constraint-validates", table_name)
                m = re.match(r"ADD\s+(?:COLUMN\s+)?(?:IF\s+NOT\s+EXISTS\s+)?" + NOT_COLUMN + IDENT + r"\s+(.*)", act, re.I | re.S)
                if m and table_name not in created:
                    rest = m.group(2).upper()
                    if "NOT NULL" in rest and not re.search(r"\b(DEFAULT|GENERATED|SERIAL|BIGSERIAL|SMALLSERIAL|IDENTITY|AUTO_INCREMENT)\b", rest):
                        add("not-null-no-default", f"{table_name}.{clean(m.group(1))}")
    if kinds == {"schema", "data"}:
        found.append(("schema-and-data", stmts[0][0], path.name, ""))
    if not down_inside and not has_sibling_down(path):
        found.append(("no-way-back", 1, path.name, ""))
    if engine != "postgres":
        found = [f for f in found if f[0] not in POSTGRES_ONLY]
    return found, old_names, len(stmts)


def references(code, names):
    hits = {}
    patterns = {n: re.compile(r"\b" + re.escape(n) + r"\b") for n in set(names) if len(n) >= 3}
    for folder, dirs, files in os.walk(code):
        dirs[:] = [d for d in dirs if d not in SKIP]
        for name in files:
            path = pathlib.Path(folder, name)
            if path.suffix not in SOURCE:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for n, pattern in patterns.items():
                if pattern.search(text):
                    hits.setdefault(n, []).append(path.relative_to(code).as_posix())
    return hits


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="+", type=pathlib.Path, help=".sql files or folders holding the pending migrations")
    parser.add_argument("--code", type=pathlib.Path, help="source folder to search for old table and column names")
    parser.add_argument("--forward-only", action="store_true", help="the project never runs down migrations; do not block on a missing one")
    parser.add_argument("--engine", default="postgres", choices=["postgres", "mysql", "sqlite", "other"], help="database engine (default postgres)")
    parser.add_argument("--json", action="store_true", help="print findings as JSON")
    args = parser.parse_args()

    files = []
    for path in args.paths:
        if path.is_dir():
            files += sorted(p for p in path.rglob("*.sql") if p.is_file())
        elif path.is_file() and path.suffix.lower() == ".sql":
            files.append(path)
        elif path.is_file():
            print(f"RESULT not verified: {path} is not a .sql file. Ask the migration tool to print the SQL it would run and check that file.")
            return 2
        else:
            print(f"blocked: {path} does not exist")
            return 2
    ups = [f for f in files if not is_down_file(f)]
    if not ups:
        print("blocked: no up migration (.sql) found in the paths given")
        return 2
    if args.code and not args.code.is_dir():
        print(f"blocked: --code {args.code} is not a folder")
        return 2
    created = set()
    for path in ups:
        for _, sql in statements(path.read_text(encoding="utf-8", errors="replace")):
            m = re.match(r"CREATE\s+(?:UNLOGGED\s+|TEMP\s+|TEMPORARY\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?" + IDENT, sql, re.I)
            if m:
                created.add(clean(m.group(1)))
    results, total, all_old = [], 0, []
    for path in ups:
        found, old, count = lint_file(path, created, args.engine)
        total += count
        all_old += old
        results += [(path, *f) for f in found]
    if total == 0:
        print("blocked: the files hold no SQL statements; an empty migration proves nothing")
        return 2
    refs = references(args.code, all_old) if args.code else {}
    if args.forward_only:
        results = [r for r in results if r[1] != "no-way-back"]
    blocks = [r for r in results if RULES[r[1]][0] == "BLOCK"]
    warns = [r for r in results if RULES[r[1]][0] == "WARN"]
    if args.json:
        print(json.dumps([{"file": str(p), "line": line, "rule": rule, "severity": RULES[rule][0], "detail": detail,
                           "why": RULES[rule][1], "instead": RULES[rule][2]} for p, rule, line, _, detail in results], indent=2))
    else:
        print(f"read {len(ups)} up migration file(s), {total} statements; {len(files) - len(ups)} down file(s) not linted; engine {args.engine}")
        for path, rule, line, sql, detail in blocks + warns:
            severity, why, instead = RULES[rule]
            print(f"{severity} {path}:{line} {rule}" + (f" ({detail})" if detail else ""))
            print(f"      {sql[:110]}")
            print(f"      why: {why}")
            print(f"      instead: {instead}")
        if args.code:
            for name in sorted(set(all_old)):
                where = refs.get(name)
                print(f"old name '{name}': " + (f"still used in {len(where)} source file(s): {', '.join(where[:5])}" if where else "not found in source files"))
        elif all_old:
            print("old names were not searched for in code; run again with --code <source folder>")
        if args.forward_only:
            print("forward-only: a missing down migration was not counted, on the user's word")
        print("checked: the text of the files only. Nothing was applied to any database.")
        if args.engine == "postgres":
            print("note: lock reasons describe PostgreSQL as commonly documented; they were not checked against your version's manual")
    if blocks:
        rules = sorted({b[1] for b in blocks})
        print(f"RESULT fail: {len(blocks)} blocking finding(s): {', '.join(rules)}" + (f"; {len(warns)} warning(s)" if warns else ""))
        return 1
    if args.engine != "postgres":
        print(f"RESULT not verified: lock rules are written for PostgreSQL and were skipped for {args.engine}; data-loss, rename, type and way-back rules found nothing")
        return 2
    print(f"RESULT pass: no blocking finding in {total} statements" + (f"; {len(warns)} warning(s)" if warns else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

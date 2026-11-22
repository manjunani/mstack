"""Run migration-check's sqlrules.py on migration files written by this test. No database is involved.

Usage: migration_check_cases.py <new empty folder>
"""
import argparse
import json

import harness

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("folder")
folder = harness.new_folder(parser.parse_args().folder)
tool = harness.script("migration-check", "sqlrules.py")
cases = harness.Cases("migration-check")


def write(rel, text):
    path = folder / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# 1. A careful migration with its way back in a sibling file.
write("safe/0007_add_nickname.up.sql",
      "-- adds an optional column\n"
      "ALTER TABLE users ADD COLUMN nickname text;\n"
      "ALTER TABLE users ADD COLUMN plan text NOT NULL DEFAULT 'free';\n"
      "CREATE INDEX CONCURRENTLY idx_users_nickname ON users (nickname);\n"
      "INSERT INTO notes (body) VALUES ('this text says DROP TABLE users; and it is only a string');\n")
write("safe/0007_add_nickname.down.sql", "ALTER TABLE users DROP COLUMN nickname;\nALTER TABLE users DROP COLUMN plan;\n")
code, out = harness.run(tool, folder / "safe")
cases.check("careful migration with a down file", code, 0, out, has=("1 down file(s) not linted",), lacks=("BLOCK",), last="RESULT pass")

# 2. One file with every blocking rule.
bad = write("bad/0008_cleanup.sql",
            "BEGIN;\n"
            "DROP TABLE IF EXISTS legacy_orders;\n"
            "ALTER TABLE users DROP COLUMN last_login;\n"
            "ALTER TABLE users ADD COLUMN tenant_id bigint NOT NULL;\n"
            "ALTER TABLE users ALTER COLUMN age TYPE smallint;\n"
            "ALTER TABLE users RENAME COLUMN fullname TO display_name;\n"
            "CREATE INDEX idx_users_tenant ON users (tenant_id);\n"
            "CREATE INDEX CONCURRENTLY idx_users_age ON users (age);\n"
            "/* a comment with ; inside */\n"
            "TRUNCATE audit_log;\n"
            "DELETE FROM sessions;\n"
            "UPDATE users SET plan = 'free';\n"
            "ALTER TABLE users ALTER COLUMN email SET NOT NULL;\n"
            "ALTER TABLE orders ADD CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES users (id);\n"
            "COMMIT;\n")
code, out = harness.run(tool, bad, "--json")
found = json.loads(out[:out.rindex("RESULT")])
rules = sorted({f["rule"] for f in found})
want = sorted(["drop-table", "drop-column", "not-null-no-default", "type-change", "rename", "index-blocks-writes",
               "concurrent-in-transaction", "truncate", "delete-all", "update-all", "set-not-null",
               "constraint-validates", "schema-and-data", "no-way-back"])
cases.check("every rule fires once on the bad file", code, 1, out, last="RESULT fail")
cases.check(f"rules found: {len(rules)} of {len(want)}", 0 if rules == want else 1, 0, " ".join(sorted(set(want) ^ set(rules))))
lines = {f["rule"]: f["line"] for f in found}
cases.check("line numbers point at the statement", 0 if (lines["drop-table"], lines["truncate"], lines["constraint-validates"]) == (2, 10, 14) else 1, 0, str(lines))

# 3. Old names still used by code.
write("app/models.py", "class User:\n    columns = ['id', 'fullname', 'last_login']\n")
code, out = harness.run(tool, bad, "--code", folder / "app")
cases.check("old names searched in code", code, 1, out,
            has=("old name 'fullname': still used in 1 source file(s): models.py", "old name 'legacy_orders': not found in source files"))

# 4. Down marker inside the file; drops after the marker are the way back and are not flagged.
write("marker/0009_tags.sql",
      "-- +goose Up\nCREATE TABLE tags (id bigint PRIMARY KEY, name text NOT NULL);\n"
      "CREATE INDEX idx_tags_name ON tags (name);\nALTER TABLE tags ADD COLUMN colour text NOT NULL;\n"
      "-- +goose Down\nDROP TABLE tags;\n")
code, out = harness.run(tool, folder / "marker")
cases.check("down marker in the file; new table is exempt from lock rules", code, 0, out, lacks=("BLOCK", "WARN"), last="RESULT pass")

# 5. No down migration.
write("nodown/0010_add_bio.sql", "ALTER TABLE users ADD COLUMN bio text;\n")
code, out = harness.run(tool, folder / "nodown")
cases.check("no way back", code, 1, out, has=("no-way-back",), last="RESULT fail")
code, out = harness.run(tool, folder / "nodown", "--forward-only")
cases.check("forward-only accepted on the user's word", code, 0, out, has=("forward-only:",), last="RESULT pass")

# 6. Other engines: lock rules are skipped and the result says so.
code, out = harness.run(tool, folder / "nodown", "--forward-only", "--engine", "mysql")
cases.check("mysql: lock rules skipped", code, 2, out, last="RESULT not verified")

# 7. Bad input.
empty = write("empty/0011_nothing.sql", "-- nothing here yet\n")
code, out = harness.run(tool, empty)
cases.check("file with comments only", code, 2, out, last="blocked")
code, out = harness.run(tool, folder / "missing")
cases.check("path that does not exist", code, 2, out, last="blocked")
py = write("alembic/0012_x.py", "def upgrade():\n    pass\n")
code, out = harness.run(tool, py)
cases.check("non-SQL migration file", code, 2, out, last="RESULT not verified")
write("onlydown/down.sql", "DROP TABLE x;\n")
code, out = harness.run(tool, folder / "onlydown")
cases.check("folder with only a down file", code, 2, out, last="blocked")

# 8. Dollar-quoted function body with semicolons and a quoted identifier.
write("func/0013_fn.up.sql",
      "CREATE FUNCTION touch() RETURNS trigger AS $body$\nBEGIN\n  NEW.updated := now(); DELETE FROM x;\n  RETURN NEW;\nEND;\n$body$ LANGUAGE plpgsql;\n"
      "ALTER TABLE \"Users\" DROP COLUMN \"Legacy Flag\";\n")
write("func/0013_fn.down.sql", "DROP FUNCTION touch();\n")
code, out = harness.run(tool, folder / "func")
cases.check("function body is not split; quoted names are read", code, 1, out, has=("drop-column (users.legacy flag)", "0013_fn.up.sql:7"), lacks=("delete-all",))

raise SystemExit(cases.finish())

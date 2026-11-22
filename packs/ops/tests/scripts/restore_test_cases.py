"""Run restore-test's restore.py on backups made by this test: SQLite files and dumps, tar and zip archives.

Usage: restore_test_cases.py <new empty folder>
"""
import argparse
import gzip
import hashlib
import io
import sqlite3
import tarfile
import zipfile

import harness

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("folder")
folder = harness.new_folder(parser.parse_args().folder)
tool = harness.script("restore-test", "restore.py")
cases = harness.Cases("restore-test")
root = ("--root", folder)

# A "live" database and a backup of it.
live = folder / "live.sqlite"
conn = sqlite3.connect(live)
conn.executescript("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT, created_at TEXT);"
                   "CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER, total REAL);")
conn.executemany("INSERT INTO users (email, created_at) VALUES (?, ?)", [(f"u{i}@example.test", f"2026-11-{1 + i % 20:02d}T10:00:00") for i in range(40)])
conn.executemany("INSERT INTO orders (user_id, total) VALUES (?, ?)", [(1 + i % 40, i * 1.5) for i in range(250)])
conn.commit()
backup = folder / "backup.sqlite"
with sqlite3.connect(backup) as copy:
    conn.backup(copy)
dump = folder / "backup.sql"
dump.write_text("\n".join(conn.iterdump()) + "\n", encoding="utf-8")
conn.close()
live_sum = hashlib.sha256(live.read_bytes()).hexdigest()
backup_sum = hashlib.sha256(backup.read_bytes()).hexdigest()

code, out = harness.run(tool, *root, "sqlite", backup, "--expect", "users=40", "--expect", "orders>=200", "--newest", "users.created_at")
cases.check("database file restores and counts match", code, 0, out, has=("users: 40 rows", "orders: 250 rows", "integrity check: ok", "newest users.created_at: 2026-11-20"), last="RESULT pass")
scratch = sorted((folder / ".mstack" / "restore-test").iterdir())
cases.check("scratch copy is in a new folder under .mstack", 0 if len(scratch) == 1 and (scratch[0] / "restored.sqlite").is_file() else 1, 0)
cases.check("backup and live file are unchanged", 0 if hashlib.sha256(live.read_bytes()).hexdigest() == live_sum and hashlib.sha256(backup.read_bytes()).hexdigest() == backup_sum else 1, 0)
cases.check(".mstack/.gitignore lists restore-test/", 0 if "restore-test/" in (folder / ".mstack" / ".gitignore").read_text() else 1, 0)

code, out = harness.run(tool, *root, "sqlite", dump, "--expect", "users=40")
cases.check("SQL dump restores", code, 0, out, has=("SQL dump",), last="RESULT pass")

gz = folder / "backup.sql.gz"
gz.write_bytes(gzip.compress(dump.read_bytes()))
code, out = harness.run(tool, *root, "sqlite", gz, "--expect", "orders=250")
cases.check("gzipped dump restores", code, 0, out, last="RESULT pass")

code, out = harness.run(tool, *root, "sqlite", backup, "--expect", "users=4000")
cases.check("fewer rows than expected", code, 1, out, has=("FAIL users: 40 rows, expected = 4000",), last="RESULT fail")
code, out = harness.run(tool, *root, "sqlite", backup, "--expect", "users=41", "--tolerance", "5")
cases.check("inside the stated tolerance", code, 0, out, last="RESULT pass")
code, out = harness.run(tool, *root, "sqlite", backup, "--expect", "invoices>=1")
cases.check("expected table is absent", code, 1, out, has=("not in the restored data",), last="RESULT fail")
code, out = harness.run(tool, *root, "sqlite", backup)
cases.check("no expected counts stated", code, 2, out, last="RESULT not verified")

# A backup cut short: the common real failure.
cut = folder / "cut.sqlite"
cut.write_bytes(backup.read_bytes()[: backup.stat().st_size // 2])
code, out = harness.run(tool, *root, "sqlite", cut, "--expect", "users=40")
cases.check("truncated database file", code, 1, out, last="RESULT fail")
cut_dump = folder / "cut.sql"
cut_dump.write_text(dump.read_text()[: len(dump.read_text()) // 2], encoding="utf-8")
code, out = harness.run(tool, *root, "sqlite", cut_dump, "--expect", "orders=250")
cases.check("truncated dump", code, 1, out, last="RESULT fail")
(folder / "zero.sqlite").write_bytes(b"")
code, out = harness.run(tool, *root, "sqlite", folder / "zero.sqlite", "--expect", "users=40")
cases.check("empty backup file", code, 1, out, last="RESULT fail")
code, out = harness.run(tool, *root, "sqlite", folder / "none.sqlite", "--expect", "users=40")
cases.check("no backup file", code, 2, out, last="blocked")

# A dump that tries to reach another file is stopped.
other = folder / "other.sqlite"
hostile = folder / "hostile.sql"
hostile.write_text(f"CREATE TABLE a (x);\nATTACH DATABASE '{other}' AS o;\nCREATE TABLE o.b (y);\n", encoding="utf-8")
code, out = harness.run(tool, *root, "sqlite", hostile, "--expect", "a=0")
cases.check("dump may not attach another database", code, 1, out, last="RESULT fail")
cases.check("the other file was not created", 1 if other.exists() else 0, 0)

# Archives.
site = folder / "site"
(site / "uploads").mkdir(parents=True)
(site / "data").mkdir()
for i in range(12):
    (site / "uploads" / f"img{i}.bin").write_bytes(bytes([i]) * 100)
(site / "data" / "app.db").write_bytes(b"x" * 500)
tar_path = folder / "site.tar.gz"
with tarfile.open(tar_path, "w:gz") as t:
    t.add(site, arcname="site")
sums = folder / "sums.txt"
sums.write_text("".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  site/{p.relative_to(site).as_posix()}\n" for p in sorted(site.rglob("*")) if p.is_file()), encoding="utf-8")

code, out = harness.run(tool, *root, "archive", tar_path, "--expect-files", "13", "--expect-path", "site/data/app.db", "--expect-path", "site/uploads", "--manifest", sums)
cases.check("tar archive restores; count, paths and sums match", code, 0, out, has=("13 files", "manifest: 13 sums checked"), last="RESULT pass")
code, out = harness.run(tool, *root, "archive", tar_path, "--expect-files", ">=500")
cases.check("fewer files than expected", code, 1, out, last="RESULT fail")
code, out = harness.run(tool, *root, "archive", tar_path, "--expect-path", "site/data/missing.db")
cases.check("expected path is absent", code, 1, out, last="RESULT fail")
code, out = harness.run(tool, *root, "archive", tar_path)
cases.check("archive with nothing expected", code, 2, out, last="RESULT not verified")
bad_sums = folder / "bad-sums.txt"
bad_sums.write_text(("0" * 64) + "  site/data/app.db\n", encoding="utf-8")
code, out = harness.run(tool, *root, "archive", tar_path, "--manifest", bad_sums)
cases.check("sum differs from the manifest", code, 1, out, has=("content differs",), last="RESULT fail")

zip_path = folder / "site.zip"
with zipfile.ZipFile(zip_path, "w") as z:
    z.writestr("site/data/app.db", b"x" * 500)
    z.writestr("../escape.txt", b"outside")
code, out = harness.run(tool, *root, "archive", zip_path, "--expect-files", "1")
cases.check("zip restores; the entry that leaves the folder is skipped", code, 0, out, has=("1 entries skipped",), last="RESULT pass")
cases.check("nothing was written outside the scratch folder", 1 if list(folder.rglob("escape.txt")) else 0, 0)

evil = folder / "evil.tar"
with tarfile.open(evil, "w") as t:
    info = tarfile.TarInfo("../../escape2.txt")
    info.size = 3
    t.addfile(info, io.BytesIO(b"out"))
code, out = harness.run(tool, *root, "archive", evil, "--expect-files", ">=1")
cases.check("tar whose only entry leaves the folder", code, 1, out, has=("holds no files",), last="RESULT fail")
(folder / "broken.tar.gz").write_bytes(tar_path.read_bytes()[:200])
code, out = harness.run(tool, *root, "archive", folder / "broken.tar.gz", "--expect-files", "13")
cases.check("truncated archive", code, 1, out, last="RESULT fail")

# Checklist for engines the script cannot restore.
code, out = harness.run(tool, "checklist", "--engine", "postgres")
cases.check("checklist alone is not verified", code, 2, out, has=("[ ] 1.", "pg_restore", "unverified"), last="RESULT not verified")
evidence = folder / "counts.txt"
evidence.write_text(" table  | count\n--------+-------\n users  | 1200\n orders | 5311\n(2 rows)\n", encoding="utf-8")
code, out = harness.run(tool, "checklist", "--engine", "postgres", "--evidence", evidence, "--scratch-name", "restore_test_20261122", "--expect", "users=1200", "--expect", "orders>=5000")
cases.check("user-supplied counts meet expectations", code, 0, out, has=("did not run the restore",), last="RESULT pass")
code, out = harness.run(tool, "checklist", "--evidence", evidence, "--scratch-name", "restore_test_20261122", "--expect", "users=1300")
cases.check("user-supplied counts are short", code, 1, out, last="RESULT fail")
code, out = harness.run(tool, "checklist", "--evidence", evidence, "--scratch-name", "app_production", "--expect", "users=1200")
cases.check("restore target named like a live database", code, 2, out, last="blocked")
code, out = harness.run(tool, "checklist", "--evidence", evidence, "--scratch-name", "restore_test_x")
cases.check("evidence with nothing expected", code, 2, out, last="blocked")

raise SystemExit(cases.finish())

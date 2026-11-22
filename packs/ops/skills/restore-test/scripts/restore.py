#!/usr/bin/env python3
"""Restore a backup into a NEW scratch folder and check that the data is in it.

  restore.py sqlite BACKUP --expect users=1200 --expect "orders>=5000" [--tolerance PCT] [--newest orders.created_at]
      BACKUP is a SQLite database file or a .sql dump (either may be gzipped). It is copied or loaded into
      .mstack/restore-test/<time>-<name>/restored.sqlite, then: integrity check, foreign key check, a row
      count per table, and each count compared with what you expect.

  restore.py archive FILE --expect-files ">=120" --expect-path data/app.db [--manifest sums.txt]
      FILE is a tar (any compression) or zip archive of a folder. It is unpacked into a new scratch folder,
      then: file count, expected paths present and not empty, and optional sha256 sums ("<sum>  <path>" lines).

  restore.py checklist --engine postgres [--evidence FILE --scratch-name NAME --expect users=1200 ...]
      For databases this script cannot restore itself. Prints the restore-and-verify steps. Without
      --evidence the result is not verified. With --evidence (the count output the user saved after running
      the steps on a scratch database) the counts in it are compared with --expect.

The backup is only read. The scratch folder is always new; the script refuses to write into an existing one,
so it cannot restore over a live database. It deletes nothing: the scratch copy stays until the user removes it.
Without expected counts or paths the result is not verified: an intact file is not proof the data is there.

Exit codes: 0 = restored and every expectation met, 1 = a check failed, 2 = not verified or blocked.
"""
import argparse
import datetime
import gzip
import hashlib
import json
import pathlib
import re
import shutil
import sqlite3
import sys
import tarfile
import time
import zipfile

ENGINES = pathlib.Path(__file__).resolve().parent.parent / "references" / "engines.json"
NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
LIVE_NAME = re.compile(r"prod|live|primary|master", re.I)


def blocked(text):
    print(f"blocked: {text}")
    return 2


def scratch_folder(root, backup):
    base = root.resolve() / ".mstack"
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S")
    label = f"{stamp}-{re.sub(r'[^A-Za-z0-9_.-]', '_', backup.name)[:40]}"
    folder = None
    for attempt in range(1, 100):  # two runs in the same second get -2, -3; an existing folder is never reused
        candidate = base / "restore-test" / (label if attempt == 1 else f"{label}-{attempt}")
        try:
            candidate.mkdir(parents=True)
        except FileExistsError:
            continue
        folder = candidate
        break
    if folder is None:
        return None
    ignore = base / ".gitignore"
    have = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
    if "restore-test/" not in have.split():
        ignore.write_text(have + ("" if have.endswith("\n") or not have else "\n") + "restore-test/\n", encoding="utf-8")
    return folder


def parse_expect(items):
    """'users=1200' or 'orders>=5000' -> {name: (operator, number)}; None on bad input."""
    out = {}
    for item in items or []:
        m = re.fullmatch(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*(>=|=)\s*(\d+)\s*", item)
        if not m:
            return None
        out[m.group(1)] = (m.group(2), int(m.group(3)))
    return out


def compare(expect, counts, tolerance):
    """Return a list of failure texts; prints one line per expectation."""
    failures = []
    for name, (op, want) in expect.items():
        got = counts.get(name)
        if got is None:
            failures.append(f"{name}: not in the restored data")
            print(f"  FAIL {name}: expected {op} {want}, but it is not in the restored data")
            continue
        slack = want * tolerance / 100
        ok = got >= want if op == ">=" else abs(got - want) <= slack
        print(f"  {'ok  ' if ok else 'FAIL'} {name}: {got} rows, expected {op} {want}" + (f" (within {tolerance:g}%)" if tolerance and op == "=" else ""))
        if not ok:
            failures.append(f"{name}: {got} rows, expected {op} {want}")
    return failures


def deny_attach(action, *_):
    return sqlite3.SQLITE_DENY if action in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH) else sqlite3.SQLITE_OK


def cmd_sqlite(args):
    backup = args.backup
    if not backup.is_file():
        return blocked(f"no backup file at {backup}. If no backup exists, that is the finding to report.")
    expect = parse_expect(args.expect)
    if expect is None:
        return blocked("--expect takes table=count or table>=count")
    if backup.stat().st_size == 0:
        print("RESULT fail: the backup file is empty (0 bytes)")
        return 1
    folder = scratch_folder(args.root, backup)
    if folder is None:
        return blocked("the scratch folder already exists; wait a second and run again")
    target = folder / "restored.sqlite"
    begin = time.perf_counter()
    opener = gzip.open if backup.suffix == ".gz" else open
    try:
        with opener(backup, "rb") as src:
            head = src.read(16)
    except OSError as exc:
        print(f"RESULT fail: the backup cannot be read: {exc}")
        return 1
    kind = "database file" if head.startswith(b"SQLite format 3\x00") else "SQL dump"
    print(f"backup: {backup} ({backup.stat().st_size} bytes, {kind}); read only")
    print(f"scratch: {target} (new folder)")
    try:
        if kind == "database file":
            with opener(backup, "rb") as src, open(target, "xb") as dst:
                shutil.copyfileobj(src, dst)
            wal = backup.with_name(backup.name + "-wal")
            if wal.is_file():
                shutil.copyfile(wal, folder / "restored.sqlite-wal")
                print("  note: a -wal file sits beside the backup and was copied too; a backup made by copying only the main file of a busy database can miss recent writes")
            conn = sqlite3.connect(target)
        else:
            with opener(backup, "rb") as src:
                dump = src.read().decode("utf-8", "replace")
            conn = sqlite3.connect(target)
            conn.set_authorizer(deny_attach)
            conn.executescript(dump)
            conn.commit()
        integrity = [row[0] for row in conn.execute("PRAGMA integrity_check")]
        foreign = conn.execute("PRAGMA foreign_key_check").fetchall()
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        counts = {t: conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}
        newest = None
        if args.newest:
            table, _, column = args.newest.partition(".")
            if not (NAME.match(table) and NAME.match(column)) or table not in counts:
                print(f"  note: --newest {args.newest} names no table.column in the restored data")
            else:
                newest = conn.execute(f'SELECT max("{column}") FROM "{table}"').fetchone()[0]
        conn.close()
    except (sqlite3.Error, OSError, EOFError) as exc:
        print(f"RESULT fail: the restore did not complete: {exc}")
        return 1
    seconds = round(time.perf_counter() - begin, 2)
    print(f"restored in {seconds} s; {len(tables)} tables, {sum(counts.values())} rows in total")
    for table in tables:
        print(f"  {table}: {counts[table]} rows")
    if args.newest and newest is not None:
        print(f"newest {args.newest}: {newest}  (compare with the time the backup was taken)")
    failures = []
    if integrity != ["ok"]:
        failures.append("integrity check: " + "; ".join(integrity[:3]))
    if foreign:
        failures.append(f"foreign key check: {len(foreign)} broken reference(s)")
    if not tables:
        failures.append("the restored database has no tables")
    print(f"integrity check: {'ok' if integrity == ['ok'] else 'FAILED'}; foreign key check: {len(foreign)} broken")
    failures += compare(expect, counts, args.tolerance)
    return finish(failures, bool(expect), folder, "no expected row counts were stated, so only 'the file restores and is intact' is proven")


def finish(failures, has_expectations, folder, missing_text):
    print(f"the scratch copy holds real data and stays at {folder}; remove it with safe-delete when the test is over")
    if failures:
        print("RESULT fail: " + failures[0] + (f" (and {len(failures) - 1} more)" if len(failures) > 1 else ""))
        return 1
    if not has_expectations:
        print("RESULT not verified: " + missing_text)
        return 2
    print("RESULT pass: restored into a scratch folder and every expectation was met")
    return 0


def safe_member(name):
    path = pathlib.PurePosixPath(name.replace("\\", "/"))
    return not path.is_absolute() and ".." not in path.parts and not re.match(r"^[A-Za-z]:", name)


def cmd_archive(args):
    archive = args.file
    if not archive.is_file():
        return blocked(f"no archive at {archive}. If no backup exists, that is the finding to report.")
    m = re.fullmatch(r"\s*(>=)?\s*(\d+)\s*", args.expect_files or "0")
    if not m:
        return blocked("--expect-files takes a number or >=number")
    folder = scratch_folder(args.root, archive)
    if folder is None:
        return blocked("the scratch folder already exists; wait a second and run again")
    out = folder / "restored"
    out.mkdir()
    print(f"archive: {archive} ({archive.stat().st_size} bytes); read only")
    print(f"scratch: {out} (new folder)")
    begin, skipped = time.perf_counter(), 0
    try:
        if zipfile.is_zipfile(archive):
            with zipfile.ZipFile(archive) as z:
                names = [n for n in z.namelist() if safe_member(n)]
                skipped = len(z.namelist()) - len(names)
                z.extractall(out, members=names)
        elif tarfile.is_tarfile(archive):
            with tarfile.open(archive) as t:
                members = [mem for mem in t.getmembers() if safe_member(mem.name) and (mem.isfile() or mem.isdir())]
                skipped = len(t.getmembers()) - len(members)
                t.extractall(out, members=members, filter="data")
        else:
            print("RESULT fail: the file is neither a tar nor a zip archive, or it is damaged")
            return 1
    except (tarfile.TarError, zipfile.BadZipFile, OSError, EOFError) as exc:
        print(f"RESULT fail: the archive did not unpack: {exc}")
        return 1
    files = [p for p in out.rglob("*") if p.is_file()]
    size = sum(p.stat().st_size for p in files)
    print(f"restored in {round(time.perf_counter() - begin, 2)} s; {len(files)} files, {size} bytes" +
          (f"; {skipped} entries skipped (links, devices or paths that leave the folder)" if skipped else ""))
    failures = []
    if not files:
        failures.append("the archive holds no files")
    want = int(m.group(2))
    if args.expect_files:
        ok = len(files) >= want if m.group(1) else len(files) == want
        print(f"  {'ok  ' if ok else 'FAIL'} file count {len(files)}, expected {args.expect_files}")
        if not ok:
            failures.append(f"file count {len(files)}, expected {args.expect_files}")
    for rel in args.expect_path or []:
        path = out / rel
        ok = (path.is_file() and path.stat().st_size > 0) or (path.is_dir() and any(p.is_file() for p in path.rglob("*")))
        print(f"  {'ok  ' if ok else 'FAIL'} {rel}" + ("" if ok else ": missing or empty"))
        if not ok:
            failures.append(f"{rel} is missing or empty")
    sums = 0
    if args.manifest:
        if not args.manifest.is_file():
            return blocked(f"no manifest at {args.manifest}")
        for line in args.manifest.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.split(None, 1)
            if len(parts) != 2 or not re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
                continue
            sums += 1
            path = out / parts[1].strip().lstrip("*")
            got = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
            if got != parts[0].lower():
                failures.append(f"{parts[1].strip()}: " + ("content differs from the manifest" if got else "in the manifest, not in the archive"))
                print(f"  FAIL {failures[-1]}")
        print(f"  manifest: {sums} sums checked")
    stated = bool(args.expect_files or args.expect_path or sums)
    return finish(failures, stated, folder, "no expected file count, path or manifest was stated, so only 'the archive unpacks' is proven")


def cmd_checklist(args):
    try:
        data = json.loads(ENGINES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return blocked(f"cannot read {ENGINES}")
    engine = data["engines"].get(args.engine, data["engines"]["other"])
    expect = parse_expect(args.expect)
    if expect is None:
        return blocked("--expect takes table=count or table>=count")
    if not args.evidence:
        print(f"Restore test for {args.engine}: steps for the user to run. This script runs none of them.")
        for number, step in enumerate(data["steps"], 1):
            print(f"  [ ] {number}. {step.replace('{restore}', engine['restore']).replace('{client}', engine['client'])}")
        if not data.get("verified"):
            print(f"  note: tool names were written from memory on {data['checked']} and are unverified; read each tool's own help first")
        print("RESULT not verified: the restore was not run. Run the steps on a scratch database, save the count output to a file, and run again with --evidence FILE --scratch-name NAME --expect table=count")
        return 2
    if not args.evidence.is_file():
        return blocked(f"no evidence file at {args.evidence}")
    if not args.scratch_name:
        return blocked("give --scratch-name: the name of the database the backup was restored into")
    if LIVE_NAME.search(args.scratch_name):
        return blocked(f"'{args.scratch_name}' is named like a live database. A restore test goes into a scratch database with a name that cannot be mistaken.")
    if not expect:
        return blocked("give at least one --expect table=count so the output can be judged")
    counts = {}
    for line in args.evidence.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.fullmatch(r"\s*\|?\s*([A-Za-z_][\w.]*)\s*[|,:=\t ]\s*(\d+)\s*\|?\s*", line)
        if m:
            counts[m.group(1).split(".")[-1]] = int(m.group(2))
    print(f"evidence: {args.evidence} ({len(counts)} table counts read); restored into '{args.scratch_name}' by the user")
    failures = compare(expect, counts, args.tolerance)
    if failures:
        print("RESULT fail: " + failures[0] + (f" (and {len(failures) - 1} more)" if len(failures) > 1 else ""))
        return 1
    print("RESULT pass: the counts in the output the user supplied meet every expectation (this script did not run the restore)")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path.cwd(), help="project folder; the scratch copy goes under its .mstack/ (default: current folder)")
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("sqlite", help="restore a SQLite file or dump into a scratch folder and count rows")
    p.add_argument("backup", type=pathlib.Path)
    p.add_argument("--expect", action="append", metavar="TABLE=COUNT", help="expected rows; table=N or table>=N; repeat per table")
    p.add_argument("--tolerance", type=float, default=0.0, help="percent a count may differ from table=N (default 0)")
    p.add_argument("--newest", metavar="TABLE.COLUMN", help="print the largest value of this column, such as a created-at time")
    p = sub.add_parser("archive", help="unpack a tar or zip archive into a scratch folder and check its content")
    p.add_argument("file", type=pathlib.Path)
    p.add_argument("--expect-files", metavar="N", help="expected number of files; N or >=N")
    p.add_argument("--expect-path", action="append", metavar="PATH", help="a file or folder that must exist and not be empty; repeatable")
    p.add_argument("--manifest", type=pathlib.Path, help="file of sha256 sums to check the restored files against")
    p = sub.add_parser("checklist", help="print the steps for another database, or judge the output the user saved")
    p.add_argument("--engine", default="other", help="postgres, mysql, mongodb or other")
    p.add_argument("--evidence", type=pathlib.Path, help="file holding 'table count' lines from the scratch database")
    p.add_argument("--scratch-name", help="name of the scratch database the user restored into")
    p.add_argument("--expect", action="append", metavar="TABLE=COUNT")
    p.add_argument("--tolerance", type=float, default=0.0)
    args = parser.parse_args()
    return {"sqlite": cmd_sqlite, "archive": cmd_archive, "checklist": cmd_checklist}[args.action](args)


if __name__ == "__main__":
    sys.exit(main())

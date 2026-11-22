#!/usr/bin/env python3
"""Measure a built app by part and by file, keep a baseline, and show what grew since the baseline.

  measure PATH [--save] [--replace]   PATH is an .app bundle (iOS or macOS) or an .ipa / .zip
                                      prints the total, each top-level part and the largest files
                                      --save keeps the measurement as the baseline
  compare PATH [limits]               measures PATH and compares it with the saved baseline:
                                      total change, change per part, files that grew, new files,
                                      removed files

Sizes are the bytes of each file as stored (not disk blocks). Symbolic links count as 0 and
are counted separately. For an .ipa the uncompressed size of each entry is measured and the
archive's own compressed total is shown beside it. Neither number is the size the App Store
shows a user: the store thins, encrypts and recompresses. The store's own size report is the
source for that.

Limits are the user's own. Without a limit, `compare` only reports and passes.
  --max-bytes N             fail when the new total is above N bytes
  --max-growth-bytes N      fail when the total grew by more than N bytes
  --max-growth-percent P    fail when the total grew by more than P percent

The baseline lives in .mstack/app-size/<name>.json under the current folder (--state changes
that). --save refuses to replace an existing baseline; --replace keeps the old one under a
dated name first. The app itself is only read.

Exit codes: 0 = measured, or compared within the limits given (or no limit given)
            1 = a limit was passed, or the bundle holds no files
            2 = blocked or not verified: no such path, not an app, no baseline to compare with
"""
import argparse
import datetime
import json
import os
import pathlib
import plistlib
import re
import sys
import zipfile


def human(n):
    sign = "-" if n < 0 else ""
    n = abs(n)
    for unit, size in (("GB", 10 ** 9), ("MB", 10 ** 6), ("kB", 10 ** 3)):
        if n >= size:
            return f"{sign}{n / size:.2f} {unit}"
    return f"{sign}{n} B"


def part_of(rel, executable, mac):
    """Name the top-level part a file belongs to."""
    pieces = rel.split("/")
    if mac and pieces[0] == "Contents":
        if len(pieces) == 2:
            return "Contents (loose files)"
        return "Contents/" + pieces[1]
    if len(pieces) == 1:
        if rel == executable:
            return f"{rel} (executable)"
        if rel == "Assets.car":
            return "Assets.car"
        return "(loose files)"
    if pieces[0].endswith(".lproj"):
        return "*.lproj (translations)"
    return pieces[0] + "/"


def measure_folder(app):
    files, links = {}, 0
    for root, dirs, names in os.walk(app, followlinks=False):
        for name in list(dirs):
            if os.path.islink(os.path.join(root, name)):
                links += 1
        for name in names:
            full = os.path.join(root, name)
            rel = os.path.relpath(full, app).replace(os.sep, "/")
            if os.path.islink(full):
                links += 1
            elif os.path.isfile(full):
                files[rel] = os.path.getsize(full)
    mac = (app / "Contents" / "Info.plist").is_file()
    executable = ""
    plist = app / ("Contents/Info.plist" if mac else "Info.plist")
    try:
        with plist.open("rb") as handle:
            executable = str(plistlib.load(handle).get("CFBundleExecutable", ""))
    except (OSError, plistlib.InvalidFileException, ValueError):
        pass
    return {"kind": "macOS app bundle" if mac else "app bundle", "files": files, "links": links, "mac": mac, "executable": executable}


def measure_archive(path):
    """Return (measurement, problem) for an .ipa or .zip."""
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        return None, f"{path} is not a readable zip archive ({exc})"
    with archive:
        infos = [i for i in archive.infolist() if not i.is_dir()]
        roots = sorted({m.group(1) for m in (re.match(r"^((?:Payload/)?[^/]+\.app)/", i.filename) for i in infos) if m})
        if not roots:
            return None, f"{path} holds no .app folder (an .ipa has Payload/<Name>.app/)"
        root = roots[0] + "/"
        files, packed, links, executable = {}, 0, 0, ""
        for info in infos:
            if not info.filename.startswith(root):
                continue
            rel = info.filename[len(root):]
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                links += 1
                continue
            files[rel] = info.file_size
            packed += info.compress_size
        mac = "Contents/Info.plist" in files
        try:
            executable = str(plistlib.loads(archive.read(root + ("Contents/Info.plist" if mac else "Info.plist"))).get("CFBundleExecutable", ""))
        except (KeyError, plistlib.InvalidFileException, ValueError):
            pass
    note = f"; {len(roots)} apps in the archive, measured {roots[0]}" if len(roots) > 1 else ""
    return {"kind": f"archive ({roots[0]}{note})", "files": files, "links": links, "mac": mac, "executable": executable,
            "archive_bytes": os.path.getsize(path), "packed": packed}, None


def measure(path):
    """Return (measurement, exit code, message)."""
    target = pathlib.Path(path)
    if not target.exists():
        return None, 2, f"blocked: nothing at {target}. Give the built .app or the .ipa."
    if target.is_dir():
        if target.suffix != ".app":
            return None, 2, f"blocked: {target} is a folder but not an .app bundle"
        data = measure_folder(target)
    elif target.suffix.lower() in (".ipa", ".zip"):
        data, problem = measure_archive(target)
        if problem:
            return None, 2, f"RESULT not verified: {problem}"
    else:
        return None, 2, f"blocked: {target} is neither an .app bundle nor an .ipa or .zip archive"
    if not data["files"]:
        return None, 1, f"RESULT fail: {target} holds no files; this is not a finished build"
    parts = {}
    for rel, size in data["files"].items():
        name = part_of(rel, data["executable"], data["mac"])
        parts[name] = parts.get(name, 0) + size
    data.update(path=str(target.resolve()), total=sum(data["files"].values()), parts=parts,
                measured=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"))
    return data, 0, ""


def show(data, top):
    total = data["total"]
    print(f"measured: {data['path']} ({data['kind']})")
    print(f"total: {total} bytes ({human(total)}) in {len(data['files'])} files" + (f"; {data['links']} symbolic links counted as 0" if data["links"] else ""))
    if "packed" in data:
        print(f"archive: {data['archive_bytes']} bytes on disk; the app's entries compress to {data['packed']} bytes ({human(data['packed'])}). This is the zip's own compression, not the store's.")
    print("parts:")
    for name, size in sorted(data["parts"].items(), key=lambda kv: -kv[1]):
        print(f"  {size:>13}  {size / total:6.1%}  {name}")
    print(f"largest {min(top, len(data['files']))} files:")
    for rel, size in sorted(data["files"].items(), key=lambda kv: -kv[1])[:top]:
        print(f"  {size:>13}  {size / total:6.1%}  {rel}")


def baseline_path(state, name):
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "app"
    return pathlib.Path(state) / f"{safe}.json"


def cmd_measure(args):
    data, code, message = measure(args.path)
    if data is None:
        print(message)
        return code
    show(data, args.top)
    name = args.name or pathlib.Path(args.path).stem
    target = baseline_path(args.state, name)
    if not args.save and not args.replace:
        print(f"RESULT pass: measured {human(data['total'])}; not saved (use --save to keep it as the baseline '{name}')")
        return 0
    if target.exists():
        if not args.replace:
            old = json.loads(target.read_text(encoding="utf-8"))
            print(f"blocked: a baseline '{name}' exists ({human(old['total'])}, measured {old['measured']}). "
                  "Run `compare`, or pass --replace to make this build the new baseline; the old one is kept under a dated name.")
            return 2
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        kept = target.with_name(f"{target.stem}.{stamp}.json")
        n = 1
        while kept.exists():
            n += 1
            kept = target.with_name(f"{target.stem}.{stamp}-{n}.json")
        target.rename(kept)
        print(f"old baseline kept as {kept}")
    target.parent.mkdir(parents=True, exist_ok=True)
    keep = {k: data[k] for k in ("path", "kind", "measured", "total", "parts", "files", "links")}
    keep.update({k: data[k] for k in ("packed", "archive_bytes") if k in data})
    target.write_text(json.dumps(keep, indent=1) + "\n", encoding="utf-8")
    print(f"baseline saved: {target}")
    print(f"RESULT pass: measured {human(data['total'])} and saved as the baseline '{name}'")
    return 0


def cmd_compare(args):
    data, code, message = measure(args.path)
    if data is None:
        print(message)
        return code
    name = args.name or pathlib.Path(args.path).stem
    target = baseline_path(args.state, name)
    if not target.is_file():
        show(data, args.top)
        print(f"RESULT not verified: no baseline '{name}' at {target}; measure the build to compare against with `measure --save` first")
        return 2
    try:
        old = json.loads(target.read_text(encoding="utf-8"))
        old_total, old_files, old_parts = old["total"], old["files"], old["parts"]
    except (ValueError, KeyError) as exc:
        print(f"RESULT not verified: the baseline {target} cannot be read ({exc})")
        return 2
    show(data, args.top)
    delta = data["total"] - old_total
    percent = delta / old_total * 100 if old_total else 0.0
    print(f"baseline: '{name}', {old_total} bytes ({human(old_total)}), measured {old.get('measured', '?')} from {old.get('path', '?')}")
    print(f"change: {delta:+} bytes ({human(delta)}, {percent:+.2f}%)")
    names = sorted(set(old_parts) | set(data["parts"]), key=lambda n: -abs(data["parts"].get(n, 0) - old_parts.get(n, 0)))
    moved = [(n, data["parts"].get(n, 0) - old_parts.get(n, 0)) for n in names]
    print("change per part:")
    for part, change in [m for m in moved if m[1]] or [("(no part changed)", 0)]:
        print(f"  {change:>+13}  {part}")
    grew = sorted(((data["files"][f] - old_files[f], f) for f in data["files"] if f in old_files and data["files"][f] > old_files[f]), reverse=True)
    shrank = sorted((data["files"][f] - old_files[f], f) for f in data["files"] if f in old_files and data["files"][f] < old_files[f])
    added = sorted(((size, f) for f, size in data["files"].items() if f not in old_files), reverse=True)
    removed = sorted(((size, f) for f, size in old_files.items() if f not in data["files"]), reverse=True)
    for title, rows, sign in (("files that grew", grew, 1), ("new files", added, 1), ("files that shrank", shrank, 1), ("removed files", removed, -1)):
        print(f"{title}: {len(rows)} ({sum(r[0] for r in rows) * sign:+} bytes)")
        for size, rel in rows[:args.top]:
            print(f"  {size * sign:>+13}  {rel}")
    over = []
    if args.max_bytes is not None and data["total"] > args.max_bytes:
        over.append(f"total {data['total']} bytes is above the limit of {args.max_bytes}")
    if args.max_growth_bytes is not None and delta > args.max_growth_bytes:
        over.append(f"growth of {delta} bytes is above the limit of {args.max_growth_bytes}")
    if args.max_growth_percent is not None and percent > args.max_growth_percent:
        over.append(f"growth of {percent:.2f}% is above the limit of {args.max_growth_percent}%")
    limits = [x for x in (args.max_bytes, args.max_growth_bytes, args.max_growth_percent) if x is not None]
    if over:
        print("RESULT fail: " + "; ".join(over))
        return 1
    if not limits:
        print(f"RESULT pass: compared with the baseline, change {delta:+} bytes ({percent:+.2f}%); no limit was given, so this is a report only")
        return 0
    print(f"RESULT pass: change {delta:+} bytes ({percent:+.2f}%) is within the {len(limits)} limit(s) given")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, text in (("measure", "measure a build"), ("compare", "measure a build and compare it with the baseline")):
        p = sub.add_parser(name, help=text)
        p.add_argument("path", help=".app bundle, .ipa or .zip")
        p.add_argument("--name", help="name of the baseline (default: the bundle's file name without extension)")
        p.add_argument("--top", type=int, default=10, help="how many files to list (default 10)")
        p.add_argument("--state", default=".mstack/app-size", help="folder for baselines (default .mstack/app-size)")
        if name == "measure":
            p.add_argument("--save", action="store_true", help="keep this measurement as the baseline")
            p.add_argument("--replace", action="store_true", help="replace an existing baseline; the old one is kept under a dated name")
        else:
            p.add_argument("--max-bytes", type=int, help="the user's limit for the total size in bytes")
            p.add_argument("--max-growth-bytes", type=int, help="the user's limit for growth in bytes")
            p.add_argument("--max-growth-percent", type=float, help="the user's limit for growth in percent")
    args = parser.parse_args()
    return {"measure": cmd_measure, "compare": cmd_compare}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())

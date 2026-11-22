#!/usr/bin/env python3
"""Read an Apple crash report and name the failing frame, or say exactly why it cannot.

  crashread.py REPORT [--binary NAME] [--dsym PATH] [--frames N]

Formats read
  .ips    one line of JSON (the header) followed by a JSON body: exception, faultingThread,
          threads[].frames[], usedImages[], lastExceptionBacktrace, asi
  .crash  the older text report: "Exception Type:", "Crashed Thread:" or "Triggered by Thread:",
          "Thread N Crashed:" with its frame lines, "Last Exception Backtrace:", "Binary Images:"

What it prints: the process and version, the exception type, signal and codes, the message
the runtime left, the crashed thread with its top frames, which frames belong to the app's
own binary (the process's executable and anything else inside its .app bundle, or the image
named with --binary), and whether those frames carry symbol names.

The failing frame is the first own frame, counted from the top, in the stack that explains
the crash: the last exception backtrace when the report has one, otherwise the crashed thread.

--dsym PATH  when own frames are only addresses: check with `dwarfdump --uuid` that the symbol
             file belongs to the build in the report, then ask `atos` for names. A symbol file
             with a different build id is refused, and both ids are printed.

It also prints what it could not parse. It never guesses a function name from an address.

Exit codes: 0 = the failing frame is named (function, and file and line when the report has them)
            1 = the file is a crash report but contradicts itself (no crashed thread, no frames)
            2 = blocked or not verified: file missing, not a crash report, own frames are
                addresses only, no own frame in the crashed stack, or the symbol file does not match
"""
import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys

FRAME = re.compile(r"^(\d+)\s+(.+?)\s+(0x[0-9a-fA-F]{6,16})\s+(.+?)\s*$")
RAW_REST = re.compile(r"^(0x[0-9a-fA-F]+|\S.*?)\s\+\s(\d+)$")
IMAGE = re.compile(r"^\s*(0x[0-9a-fA-F]+)\s+-\s+(0x[0-9a-fA-F]+)\s+\+?(.+?)\s+(?:\((.*?)\)\s+)?(?:(arm64e?|x86_64h?|i386|armv7s?|arm64_32)\s+)?<([0-9a-fA-F-]{32,36})>\s+(.*)$")


def norm_uuid(text):
    return re.sub(r"[^0-9a-f]", "", str(text).lower())


def parse_ips(text, notes):
    """Return a report dict, or None when the text is not the JSON form."""
    first, _, rest = text.partition("\n")
    header = {}
    try:
        header = json.loads(first)
        body = json.loads(rest)
    except ValueError:
        try:
            body = json.loads(text)
        except ValueError:
            return None
    if not isinstance(body, dict):
        return None
    if "threads" not in body or "exception" not in body:
        kind = header.get("bug_type") or body.get("bug_type")
        notes.append(f"JSON report of type {kind} has no exception and thread list; it is not a crash report (a hang, memory or other diagnostic report)")
        return {"format": "ips", "not_crash": True}
    images = []
    for image in body.get("usedImages", []):
        images.append({"name": image.get("name", "?"), "base": image.get("base"), "uuid": image.get("uuid", ""),
                       "arch": image.get("arch", ""), "path": image.get("path", "")})
    if not images:
        notes.append("the report lists no binary images, so frames cannot be tied to a binary")

    def frames_of(raw):
        out = []
        for index, frame in enumerate(raw or []):
            i = frame.get("imageIndex")
            image = images[i] if isinstance(i, int) and 0 <= i < len(images) else None
            if image is None:
                notes.append(f"frame {index} names image {i}, which is not in the image list")
            base = image["base"] if image and isinstance(image.get("base"), int) else None
            offset = frame.get("imageOffset")
            where = f"{frame['sourceFile']}:{frame.get('sourceLine', '?')}" if frame.get("sourceFile") else ""
            out.append({"n": index, "image": image["name"] if image else "?", "image_ref": image,
                        "address": base + offset if base is not None and isinstance(offset, int) else None,
                        "offset": offset, "symbol": frame.get("symbol"), "symbol_offset": frame.get("symbolLocation"),
                        "source": where})
        return out

    threads = body.get("threads", [])
    index = body.get("faultingThread")
    if not isinstance(index, int):
        index = next((n for n, t in enumerate(threads) if t.get("triggered")), None)
    crashed = threads[index] if isinstance(index, int) and 0 <= index < len(threads) else None
    exc = body.get("exception", {})
    term = body.get("termination", {})
    message = []
    for lines in (body.get("asi") or {}).values():
        message += [str(x) for x in (lines if isinstance(lines, list) else [lines])]
    bundle = body.get("bundleInfo", {})
    return {"format": "ips", "process": body.get("procName") or header.get("app_name"), "path": body.get("procPath", ""),
            "bundle_id": bundle.get("CFBundleIdentifier") or header.get("bundleID"),
            "version": bundle.get("CFBundleShortVersionString") or header.get("app_version"),
            "build": bundle.get("CFBundleVersion") or header.get("build_version"),
            "os": (body.get("osVersion") or {}).get("train") or header.get("os_version"), "when": body.get("captureTime") or header.get("timestamp"),
            "exception": " ".join(str(x) for x in (exc.get("type"), f"({exc['signal']})" if exc.get("signal") else None) if x),
            "codes": exc.get("codes", ""), "subtype": exc.get("subtype", ""),
            "termination": " ".join(str(term[k]) for k in ("namespace", "indicator") if term.get(k)),
            "message": message, "crashed_index": index, "thread_count": len(threads),
            "queue": crashed.get("queue", "") if crashed else "",
            "crashed": frames_of(crashed.get("frames")) if crashed else None,
            "last_exception": frames_of(body.get("lastExceptionBacktrace")) if body.get("lastExceptionBacktrace") else None,
            "images": images}


def parse_text(text, notes):
    """Return a report dict for the older text form, or None when the text is not one."""
    if not re.search(r"^Exception Type:", text, re.M) and not re.search(r"^Thread \d+ Crashed", text, re.M):
        return None

    def field(name):
        found = re.search(r"^" + re.escape(name) + r":[ \t]*(.*)$", text, re.M)
        return found.group(1).strip() if found else ""

    images = []
    section = text.split("Binary Images:", 1)[1] if "Binary Images:" in text else ""
    for line in section.splitlines():
        found = IMAGE.match(line)
        if found:
            images.append({"name": found.group(3).strip(), "base": int(found.group(1), 16), "uuid": found.group(6),
                           "arch": found.group(5) or "", "path": found.group(7).strip()})
        elif line.strip() and line.lstrip().startswith("0x"):
            notes.append(f"binary image line not understood: {line.strip()[:70]}")
    if not images:
        notes.append("no binary image lines were read, so frames cannot be tied to a binary by path")
    by_name = {i["name"]: i for i in images}

    def frames_of(block):
        out = []
        for line in block:
            if not line.strip():
                break
            found = FRAME.match(line)
            if not found:
                notes.append(f"frame line not understood: {line.strip()[:70]}")
                continue
            name, address, rest = found.group(2).strip(), int(found.group(3), 16), found.group(4)
            raw = RAW_REST.match(rest)
            unnamed = bool(raw) and (raw.group(1).startswith("0x") or raw.group(1) == name)
            source = re.search(r"\(([^()]+:\d+)\)\s*$", rest)
            symbol = None if unnamed else re.sub(r"\s\+\s\d+(\s\(.*\))?$", "", rest).strip()
            out.append({"n": int(found.group(1)), "image": name, "image_ref": by_name.get(name), "address": address,
                        "offset": None, "symbol": symbol, "symbol_offset": None, "source": source.group(1) if source else ""})
        return out

    lines = text.splitlines()
    crashed_field = field("Crashed Thread") or field("Triggered by Thread")
    number = re.match(r"\d+", crashed_field)
    index = int(number.group(0)) if number else None
    crashed = None
    for n, line in enumerate(lines):
        head = re.match(r"^Thread (\d+) Crashed", line)
        if head:
            index = int(head.group(1)) if index is None else index
            crashed = frames_of(lines[n + 1:])
            break
    last = None
    for n, line in enumerate(lines):
        if line.startswith("Last Exception Backtrace:"):
            block = lines[n + 1:]
            if block and block[0].lstrip().startswith("("):
                notes.append("the last exception backtrace is a bare list of addresses; it was not resolved")
            else:
                last = frames_of(block) or None
            break
    message = []
    if "Application Specific Information:" in text:
        for line in text.split("Application Specific Information:", 1)[1].splitlines()[1:]:
            if not line.strip():
                break
            message.append(line.strip())
    process = re.sub(r"\s*\[\d+\]$", "", field("Process"))
    version = field("Version")
    build = re.search(r"\(([^)]*)\)", version)
    queue = re.search(r"Dispatch queue:\s*(.+)$", crashed_field)
    return {"format": "text", "process": process, "path": field("Path"), "bundle_id": field("Identifier"),
            "version": version.split("(")[0].strip(), "build": build.group(1) if build else "", "os": field("OS Version"),
            "when": field("Date/Time"), "exception": field("Exception Type"), "codes": field("Exception Codes"),
            "subtype": field("Exception Subtype"), "termination": field("Termination Reason"), "message": message,
            "crashed_index": index, "thread_count": len(re.findall(r"^Thread \d+( Crashed)?:", text, re.M)),
            "queue": queue.group(1) if queue else "", "crashed": crashed, "last_exception": last, "images": images}


def own_test(report, binary):
    """Return a function that says whether a frame belongs to the app's own code."""
    process = binary or report.get("process") or ""
    bundle = re.search(r"^(.*?\.app)/", report.get("path", "") + "/")
    root = bundle.group(1) + "/" if bundle else None

    def own(frame):
        if frame["image"] == process:
            return True
        ref = frame.get("image_ref")
        return bool(not binary and root and ref and ref.get("path", "").startswith(root))
    return own


def show_frame(frame, mark=""):
    if frame["symbol"]:
        what = frame["symbol"] + (f" + {frame['symbol_offset']}" if frame["symbol_offset"] is not None else "")
        what += f" ({frame['source']})" if frame["source"] else ""
    else:
        addr = f"0x{frame['address']:x}" if frame["address"] is not None else "address unknown"
        what = f"{addr} (no symbol name)"
    return f"  {frame['n']:3}  {frame['image'][:32]:32} {what}{mark}"


def symbolicate(frames, dsym, notes):
    """Fill symbol names for frames of one image with atos. Returns (ok, message)."""
    image = frames[0]["image_ref"]
    if not image or image.get("base") is None or any(f["address"] is None for f in frames):
        return False, "the report does not give the load address needed to resolve these frames"
    dwarfdump, atos = shutil.which("dwarfdump"), shutil.which("atos")
    if not dwarfdump or not atos:
        return False, "dwarfdump and atos are needed (they come with the Xcode command-line tools); nothing was installed"
    path = pathlib.Path(dsym)
    if not path.exists():
        return False, f"no symbol file at {dsym}"
    seen = subprocess.run([dwarfdump, "--uuid", str(path)], capture_output=True, text=True)
    ids = re.findall(r"UUID:\s*([0-9A-Fa-f-]{36})\s*\(([^)]*)\)\s*(.*)", seen.stdout)
    want = norm_uuid(image.get("uuid", ""))
    match = next((entry for entry in ids if norm_uuid(entry[0]) == want), None)
    if not match:
        have = ", ".join(f"{u} ({a})" for u, a, _ in ids) or "no build id found in it"
        return False, (f"the symbol file does not belong to this build. The report's binary {image['name']} has build id "
                       f"{image.get('uuid')}; {dsym} has {have}")
    command = [atos, "-arch", match[1] or image.get("arch") or "arm64", "-o", match[2].strip() or str(path),
               "-l", hex(image["base"])] + [hex(f["address"]) for f in frames]
    done = subprocess.run(command, capture_output=True, text=True)
    names = [line.strip() for line in done.stdout.splitlines() if line.strip()]
    if done.returncode != 0 or len(names) != len(frames):
        return False, f"atos did not answer for every frame (exit {done.returncode}): {done.stderr.strip()[:200]}"
    solved = 0
    for frame, name in zip(frames, names):
        if name.startswith("0x") or name == hex(frame["address"]):
            notes.append(f"atos could not name frame {frame['n']}")
            continue
        source = re.search(r"\(([^()]+:\d+)\)\s*$", name)
        frame["symbol"] = re.sub(r"\s*\(in [^)]*\)", "", re.sub(r"\s*\([^()]+:\d+\)\s*$", "", name)).strip()
        frame["source"] = source.group(1) if source else ""
        frame["symbol_offset"] = None
        solved += 1
    return solved > 0, f"atos named {solved} of {len(frames)} frames using {match[2].strip() or dsym} (build id matches)"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("report", help="the crash report file (.ips or .crash)")
    parser.add_argument("--binary", help="name of the app's binary image, when it differs from the process name")
    parser.add_argument("--dsym", help="symbol file (.dSYM bundle or binary with debug info) for the app's binary")
    parser.add_argument("--frames", type=int, default=12, help="how many frames of the crashed thread to print (default 12)")
    args = parser.parse_args()

    path = pathlib.Path(args.report)
    if not path.is_file():
        print(f"blocked: no file at {path}. Give the path of the .ips or .crash file.")
        return 2
    text = path.read_text(encoding="utf-8", errors="replace")
    notes = []
    report = parse_ips(text, notes) or parse_text(text, notes)
    if report is None:
        print(f"RESULT not verified: {path.name} is not a crash report this script can read (neither the JSON .ips form nor the text form with 'Exception Type:')")
        return 2
    if report.get("not_crash"):
        print(f"RESULT not verified: {notes[0]}")
        return 2

    print(f"report: {path} ({'JSON .ips' if report['format'] == 'ips' else 'text'} form)")
    print(f"process: {report['process']} ({report['bundle_id'] or 'no bundle id'}) version {report['version'] or '?'} (build {report['build'] or '?'}); OS {report['os'] or '?'}; {report['when'] or 'no date'}")
    print(f"exception: {report['exception'] or 'not given'}" + (f"; codes {report['codes']}" if report["codes"] else "") + (f"; {report['subtype']}" if report["subtype"] else ""))
    if report["termination"]:
        print(f"termination: {report['termination']}")
    for line in report["message"][:6]:
        print(f"message: {line}")
    crashed = report["crashed"]
    if crashed is None:
        print(f"could not parse: the crashed thread ({report['crashed_index']}) is not among the {report['thread_count']} threads in the report")
        print("RESULT fail: the report names a crashed thread it does not contain; it may be cut short")
        return 1
    if not crashed and not report["last_exception"]:
        print("RESULT fail: the crashed thread has no frames; the report may be cut short")
        return 1
    stack, stack_name = (report["last_exception"], "last exception backtrace") if report["last_exception"] else (crashed, f"crashed thread {report['crashed_index']}")
    own = own_test(report, args.binary)
    mine = [f for f in stack if own(f)]
    unnamed = [f for f in mine if not f["symbol"]]
    solved_note = ""
    if unnamed and args.dsym:
        target = unnamed[0]["image"]
        ok, solved_note = symbolicate([f for f in unnamed if f["image"] == target], args.dsym, notes)
        unnamed = [f for f in mine if not f["symbol"]]
        if not ok:
            print(f"symbol file: {solved_note}")
            print(f"blocked: {solved_note}")
            return 2
    first = mine[0] if mine else None
    print(f"crashed thread: {report['crashed_index']}" + (f" (queue {report['queue']})" if report["queue"] else "") + f"; stack used: {stack_name}, {len(stack)} frames")
    for frame in stack[:max(1, args.frames)]:
        print(show_frame(frame, "   <- first frame from the app" if frame is first else ("   <- app" if own(frame) else "")))
    if first is not None and first["n"] >= args.frames:
        print("  ...")
        print(show_frame(first, "   <- first frame from the app"))
    if solved_note:
        print(f"symbol file: {solved_note}")
    print(f"own frames in this stack: {len(mine)} of {len(stack)}; with a symbol name: {len(mine) - len(unnamed)} of {len(mine)}")
    for note in list(dict.fromkeys(notes))[:8]:
        print(f"could not parse: {note}")

    if not mine:
        top = stack[0] if stack else None
        print(f"RESULT not verified: no frame of {args.binary or report['process']} is in the {stack_name}; its top frame is "
              f"{top['image'] + ' ' + (top['symbol'] or 'unnamed') if top else 'missing'}. If the app's binary has another name, pass --binary")
        return 2
    if not first["symbol"]:
        image = first["image_ref"] or {}
        addresses = " ".join(hex(f["address"]) for f in unnamed if f["address"] is not None and f["image"] == first["image"])
        print(f"to name these frames: find the symbol file whose build id is {image.get('uuid', 'unknown')} "
              f"(`mdfind \"com_apple_xcode_dsym_uuids == {str(image.get('uuid', '')).upper()}\"` lists it when Spotlight has seen it), then run again with --dsym PATH")
        if image.get("base") is not None and addresses:
            print(f"by hand: atos -arch {image.get('arch') or '<arch>'} -o <dSYM>/Contents/Resources/DWARF/{first['image']} -l {hex(image['base'])} {addresses}")
        print(f"RESULT not verified: the first frame from {first['image']} (frame {first['n']}) is an address with no symbol name; the matching symbol file is needed")
        return 2
    where = f" at {first['source']}" if first["source"] else " (the report gives no file and line)"
    print(f"RESULT pass: failing frame is {first['image']} {first['symbol']}{where}; frame {first['n']} of the {stack_name}; exception {report['exception'] or 'not given'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

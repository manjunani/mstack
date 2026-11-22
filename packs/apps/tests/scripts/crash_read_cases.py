"""Test crash-read's script on crash reports this test writes, and on a symbol file it compiles.

Usage: python3 crash_read_cases.py <new folder under .testrun/>

The .ips samples use the field names seen in real macOS reports on the build machine. The text
(.crash) samples are written from memory of that older format; no real file of that form was
at hand, so the text parser is proven only against these samples.
The --dsym cases compile a ten-line C file with clang to get a real binary and symbol file,
then ask the script to resolve addresses inside it. No program is crashed on purpose.
"""
import json
import re
import shutil
import subprocess
import sys

import fixtures as fx

W = fx.workdir(sys.argv)
SCRIPT = fx.SKILLS / "crash-read" / "scripts" / "crashread.py"
PY = sys.executable
c = fx.Cases("crash-read")
APP = "/private/var/containers/Bundle/Application/ABCD/Notes.app"
IMAGES = [
    {"name": "Notes", "base": 0x104000000, "uuid": "0a1b2c3d-1111-2222-3333-444455556666", "arch": "arm64", "path": f"{APP}/Notes", "source": "P", "size": 100000},
    {"name": "libswiftCore.dylib", "base": 0x190000000, "uuid": "11111111-0000-0000-0000-000000000001", "arch": "arm64e", "path": "/usr/lib/swift/libswiftCore.dylib", "source": "P", "size": 5},
    {"name": "SwiftUI", "base": 0x1a0000000, "uuid": "11111111-0000-0000-0000-000000000002", "arch": "arm64e", "path": "/System/Library/Frameworks/SwiftUI.framework/SwiftUI", "source": "P", "size": 5},
    {"name": "SyncKit", "base": 0x105000000, "uuid": "0a1b2c3d-9999-2222-3333-444455556666", "arch": "arm64", "path": f"{APP}/Frameworks/SyncKit.framework/SyncKit", "source": "P", "size": 5},
]
SYS0 = {"imageIndex": 1, "imageOffset": 4000, "symbol": "_assertionFailure(_:_:file:line:flags:)", "symbolLocation": 300}
OWN_NAMED = {"imageIndex": 0, "imageOffset": 16884, "symbol": "NoteStore.load(id:)", "symbolLocation": 124, "sourceFile": "NoteStore.swift", "sourceLine": 48}
OWN_NAMED2 = {"imageIndex": 0, "imageOffset": 20000, "symbol": "closure #1 in NoteList.body.getter", "symbolLocation": 60}
OWN_RAW = {"imageIndex": 0, "imageOffset": 16884}
OWN_RAW2 = {"imageIndex": 0, "imageOffset": 20000}
UI = {"imageIndex": 2, "imageOffset": 999, "symbol": "ViewGraph.updateOutputs()", "symbolLocation": 12}
FW = {"imageIndex": 3, "imageOffset": 512, "symbol": "SyncEngine.push()", "symbolLocation": 8}


def ips(name, frames, header=None, **body_changes):
    head = {"app_name": "Notes", "app_version": "2.1", "build_version": "57", "bug_type": "309", "os_version": "iPhone OS 18.0 (22A000)", "timestamp": "2026-11-20 10:00:00.00 +0000"}
    head.update(header or {})
    body = {"procName": "Notes", "procPath": f"{APP}/Notes", "bundleInfo": {"CFBundleIdentifier": "in.acme.notes", "CFBundleShortVersionString": "2.1", "CFBundleVersion": "57"},
            "osVersion": {"train": "iPhone OS 18.0"}, "captureTime": "2026-11-20 10:00:00.0000 +0000",
            "exception": {"type": "EXC_BREAKPOINT", "signal": "SIGTRAP", "codes": "0x0000000000000001, 0x0000000190000fa0"},
            "termination": {"namespace": "SIGNAL", "indicator": "Trace/BPT trap: 5", "code": 5},
            "asi": {"libswiftCore.dylib": ["Swift/Optional.swift:247: Fatal error: Unexpectedly found nil while unwrapping an Optional value"]},
            "faultingThread": 0,
            "threads": [{"id": 1, "queue": "com.apple.main-thread", "triggered": True, "frames": frames},
                        {"id": 2, "frames": [UI]}],
            "usedImages": IMAGES}
    body.update(body_changes)
    path = W / name
    path.write_text(json.dumps(head) + "\n" + json.dumps(body, indent=2))
    return path


def check(want, label, args, *texts):
    c.run(want, label, [PY, SCRIPT] + [str(a) for a in args])
    for text in texts:
        c.has(text)


check(0, "ips: named own frame under a system frame", [ips("named.ips", [SYS0, OWN_NAMED, OWN_NAMED2, UI])],
      "RESULT pass: failing frame is Notes NoteStore.load(id:) at NoteStore.swift:48", "exception: EXC_BREAKPOINT (SIGTRAP)",
      "Unexpectedly found nil", "own frames in this stack: 2 of 4; with a symbol name: 2 of 2", "<- first frame from the app")
check(0, "ips: named own frame with no file and line says so", [ips("noline.ips", [SYS0, OWN_NAMED2])], "the report gives no file and line")
check(2, "ips: own frames are addresses only", [ips("raw.ips", [SYS0, OWN_RAW, OWN_RAW2, UI])],
      "RESULT not verified: the first frame from Notes (frame 1) is an address", "0a1b2c3d-1111-2222-3333-444455556666",
      "atos -arch arm64 -o <dSYM>/Contents/Resources/DWARF/Notes -l 0x104000000 0x1040041f4 0x104004e20", "with a symbol name: 0 of 2")
check(2, "ips: crash entirely in system code", [ips("system.ips", [SYS0, UI])], "RESULT not verified: no frame of Notes", "top frame is libswiftCore.dylib")
check(0, "ips: a framework inside the .app counts as the app's own code", [ips("framework.ips", [SYS0, FW, OWN_NAMED])], "failing frame is SyncKit SyncEngine.push()")
check(0, "ips: --binary narrows 'own' to one image", [ips("binary.ips", [SYS0, FW, OWN_NAMED]), "--binary", "Notes"], "failing frame is Notes NoteStore.load(id:)")
check(2, "ips: --binary naming an image that is not in the stack", [W / "named.ips", "--binary", "Other"], "no frame of Other")
check(0, "ips: the last exception backtrace is used when present",
      [ips("lastexc.ips", [SYS0, UI], lastExceptionBacktrace=[SYS0, OWN_NAMED2, UI])], "stack used: last exception backtrace", "closure #1 in NoteList.body.getter")
check(0, "ips: no faultingThread, the triggered thread is used", [ips("triggered.ips", [SYS0, OWN_NAMED], faultingThread=None)], "crashed thread: 0")
check(1, "ips: crashed thread index outside the thread list", [ips("badindex.ips", [SYS0, OWN_NAMED], faultingThread=9)], "RESULT fail", "it may be cut short")
check(1, "ips: crashed thread with no frames", [ips("noframes.ips", [])], "RESULT fail: the crashed thread has no frames")
check(0, "ips: a frame pointing at a missing image is reported, the rest is read",
      [ips("badimage.ips", [{"imageIndex": 40, "imageOffset": 1}, OWN_NAMED])], "could not parse: frame 0 names image 40", "RESULT pass")
check(0, "ips: own frame far down is still found and shown", [ips("deep.ips", [SYS0] * 20 + [OWN_NAMED]), "--frames", "5"], "(frame 20)" if False else "frame 20 of the crashed thread")
other = W / "jetsam.ips"
other.write_text(json.dumps({"bug_type": "298", "os_version": "x"}) + "\n" + json.dumps({"largestProcess": "Notes", "processes": []}))
check(2, "ips: a memory report is not a crash report", [other], "RESULT not verified", "type 298")
body_only = W / "bodyonly.ips"
body_only.write_text(json.dumps(json.loads((W / "named.ips").read_text().split("\n", 1)[1])))
check(0, "ips: a file holding only the JSON body is read", [body_only], "RESULT pass")

TEXT = """Incident Identifier: 1234
Hardware Model:      iPhone15,2
Process:             Notes [4242]
Path:                {app}/Notes
Identifier:          in.acme.notes
Version:             2.1 (57)
Code Type:           ARM-64 (Native)
Date/Time:           2026-11-20 10:00:00.000 +0000
OS Version:          iPhone OS 18.0 (22A000)

Exception Type:  EXC_CRASH (SIGABRT)
Exception Codes: 0x0000000000000000, 0x0000000000000000
{thread_line}

Application Specific Information:
abort() called

Thread 0 name:  Dispatch queue: com.apple.main-thread
Thread 0 Crashed:
0   libsystem_kernel.dylib        	0x00000001b8a7c200 __pthread_kill + 8
1   libsystem_c.dylib             	0x00000001b8a11000 abort + 180
{own}
3   UIKitCore                     	0x00000001a0001000 UIApplicationMain + 340

Thread 1:
0   libsystem_kernel.dylib        	0x00000001b8a7d000 __workq_kernreturn + 8

Binary Images:
0x104000000 - 0x10400ffff Notes arm64  <0a1b2c3d111122223333444455556666> {app}/Notes
0x1b8a70000 - 0x1b8a9ffff libsystem_kernel.dylib arm64e  <22222222000000000000000000000001> /usr/lib/system/libsystem_kernel.dylib
"""


def crash(name, own, thread_line="Triggered by Thread:  0"):
    path = W / name
    path.write_text(TEXT.format(app=APP, own=own, thread_line=thread_line))
    return path


check(0, "text: named own frame with file and line", [crash("named.crash", "2   Notes                         	0x00000001040041f4 NoteStore.load(id:) + 124 (NoteStore.swift:48)")],
      "(text form)", "RESULT pass: failing frame is Notes NoteStore.load(id:) at NoteStore.swift:48", "exception: EXC_CRASH (SIGABRT)", "message: abort() called")
check(2, "text: own frame given as load address + offset", [crash("raw.crash", "2   Notes                         	0x00000001040041f4 0x104000000 + 16884")],
      "RESULT not verified", "atos -arch arm64", "-l 0x104000000 0x1040041f4")
check(2, "text: own frame given as image name + offset", [crash("raw2.crash", "2   Notes                         	0x00000001040041f4 Notes + 16884")], "address with no symbol name")
check(0, "text: macOS wording 'Crashed Thread:' with a queue", [crash("mac.crash", "2   Notes                         	0x00000001040041f4 main + 20", "Crashed Thread:        0  Dispatch queue: com.apple.main-thread")], "queue com.apple.main-thread", "RESULT pass")
check(0, "text: a frame line it cannot read is reported", [crash("odd.crash", "2   Notes                         	0x00000001040041f4 main + 20\n?? garbage line here")], "could not parse: frame line not understood")
check(2, "text: no own frame", [crash("sys.crash", "2   CoreFoundation                	0x00000001a1000000 CFRunLoopRun + 600")], "no frame of Notes")

(W / "notes.txt").write_text("the app crashed when I tapped save\n")
check(2, "a text file that is not a crash report", [W / "notes.txt"], "RESULT not verified", "not a crash report this script can read")
(W / "empty.ips").write_text("")
check(2, "an empty file", [W / "empty.ips"], "RESULT not verified")
check(2, "a missing file is blocked", [W / "nope.ips"], "blocked: no file")

clang = shutil.which("clang")
built = False
if clang and shutil.which("dwarfdump") and shutil.which("atos") and shutil.which("nm"):
    (W / "boom.c").write_text("#include <stdio.h>\nint depth = 0;\nint boom(int x) {\n  depth += x;\n  return depth * 2;\n}\nint main(void) {\n  printf(\"%d\\n\", boom(3));\n  return 0;\n}\n")
    (W / "other.c").write_text("int main(void) { return 0; }\n")
    one = subprocess.run([clang, "-g", "-O0", "-o", str(W / "boom"), str(W / "boom.c")], capture_output=True, text=True)
    two = subprocess.run([clang, "-g", "-O0", "-o", str(W / "other"), str(W / "other.c")], capture_output=True, text=True)
    built = one.returncode == 0 and two.returncode == 0 and (W / "boom.dSYM").is_dir() and (W / "other.dSYM").is_dir()
    if not built:
        print(f"not run: clang did not produce a binary with a symbol file ({(one.stderr or two.stderr).strip()[:160]})")
else:
    print("not run: clang, dwarfdump, atos or nm is missing, so the --dsym cases were skipped")
if built:
    uuid_line = subprocess.run(["dwarfdump", "--uuid", str(W / "boom.dSYM")], capture_output=True, text=True).stdout
    uuid, arch = re.search(r"UUID: ([0-9A-F-]{36}) \((\w+)\)", uuid_line).groups()
    symbols = subprocess.run(["nm", str(W / "boom")], capture_output=True, text=True).stdout
    boom_at = int(re.search(r"^([0-9a-f]+) T _boom$", symbols, re.M).group(1), 16)
    text_base = int(re.search(r"^([0-9a-f]+) T __mh_execute_header$", symbols, re.M).group(1), 16)
    images = [{"name": "boom", "base": 0x104000000, "uuid": uuid.lower(), "arch": arch, "path": "/Applications/Boom.app/Contents/MacOS/boom"}, IMAGES[1]]
    raw = ips("boom.ips", [SYS0, {"imageIndex": 0, "imageOffset": boom_at - text_base + 8}], usedImages=images,
              procName="boom", procPath="/Applications/Boom.app/Contents/MacOS/boom")
    check(2, "dsym: without --dsym the frame is an address", [raw], uuid.upper(), "run again with --dsym PATH")
    check(0, "dsym: the matching symbol file names the frame through atos", [raw, "--dsym", W / "boom.dSYM"],
          "build id matches", "RESULT pass: failing frame is boom boom at boom.c:")
    check(2, "dsym: a symbol file from another build is refused, both ids shown", [raw, "--dsym", W / "other.dSYM"],
          "does not belong to this build", uuid.lower())
    c.last_line("blocked:")
    check(2, "dsym: a path with no symbol file is blocked", [raw, "--dsym", W / "missing.dSYM"], "no symbol file at")
c.run(0, "--help works", [PY, SCRIPT, "--help"])
sys.exit(c.finish())

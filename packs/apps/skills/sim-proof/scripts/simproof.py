#!/usr/bin/env python3
"""Put a built iPhone app on a booted simulator, launch it, take a screenshot and check the picture.

  devices   list simulators and say which are booted (reads `xcrun simctl list devices --json`)
  run       install an .app bundle, launch it, wait, confirm the process is alive, take a
            screenshot with `simctl io`, check that the picture is not blank, write a record
  check     check a screenshot file only (size and pixel statistics), no simulator needed

The script does not build the app and does not boot a simulator. Building is the project's
own command; booting changes the user's machine, so the user or the calling agent does it
on purpose. When no simulator is booted the script ends as blocked and prints the choices.

What `run` proves: the bundle installed, the launch gave a process id, that process was
still alive after the wait and after the screenshot, and the screenshot is a readable PNG
that is not blank. It does not prove WHICH screen is shown. A person or the agent looks
at the picture for that.

Writes only under --out (default .mstack/sim-proof/ in the current folder).

Exit codes: 0 = every step passed
            1 = a step failed (install, launch, process died, screenshot blank or broken)
            2 = blocked or not verified (no xcrun, no booted simulator, bad input)
"""
import argparse
import datetime
import json
import os
import pathlib
import plistlib
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import pngstat  # noqa: E402

GET_XCODE = ("xcrun was not found. It comes with Xcode or the Xcode command-line tools; "
             "installing them is the user's decision. Nothing was installed.")


def call(command, timeout=180):
    """Run a command. Returns (exit code or None, stdout, stderr)."""
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "", f"no answer after {timeout} seconds"
    except OSError as exc:
        return None, "", str(exc)
    return done.returncode, done.stdout, done.stderr


def tail(text, lines=6):
    rows = [r for r in text.strip().splitlines() if r.strip()]
    return "\n".join("    | " + r for r in rows[-lines:]) or "    | (no output)"


def find_xcrun(given):
    if given:
        return given if os.path.isfile(given) and os.access(given, os.X_OK) else None
    return shutil.which("xcrun")


def list_devices(xcrun):
    """Return (devices, error). Each device: udid, name, state, runtime, available."""
    code, out, err = call([xcrun, "simctl", "list", "devices", "--json"], timeout=60)
    if code != 0:
        return None, f"`simctl list devices --json` did not work (exit {code}):\n{tail(err or out)}"
    try:
        data = json.loads(out)
        groups = data["devices"]
        if not isinstance(groups, dict):
            raise TypeError("devices is not a table")
    except (ValueError, KeyError, TypeError) as exc:
        return None, f"`simctl list devices --json` printed something that is not a device list ({exc})"
    found = []
    for runtime, entries in groups.items():
        for entry in entries if isinstance(entries, list) else []:
            if isinstance(entry, dict) and entry.get("udid"):
                found.append({"udid": entry["udid"], "name": entry.get("name", "?"),
                              "state": entry.get("state", "?"), "runtime": runtime.rsplit(".", 1)[-1],
                              "available": entry.get("isAvailable", True)})
    return found, None


def choose_device(devices, wanted):
    """Return (device, blocked message)."""
    booted = [d for d in devices if d["state"] == "Booted"]
    if wanted:
        match = [d for d in devices if d["udid"] == wanted]
        if not match:
            return None, f"no simulator has the id {wanted}. Run `devices` and use an id from the list."
        if match[0]["state"] != "Booted":
            return None, (f"simulator {match[0]['name']} ({wanted}) is not booted (state: {match[0]['state']}). "
                          f"Boot it with `xcrun simctl boot {wanted}` if the user agrees, then run again.")
        return match[0], None
    if not booted:
        ready = [d for d in devices if d["available"]]
        hint = (f"{len(ready)} simulators exist but none is booted. Boot one with `xcrun simctl boot <udid>` "
                "if the user agrees, then run again." if ready else
                "No simulator exists on this machine. A simulator runtime is installed through Xcode; that is the user's decision.")
        return None, "no booted simulator. " + hint
    if len(booted) > 1:
        names = "; ".join(f"{d['name']} {d['udid']}" for d in booted)
        return None, f"{len(booted)} simulators are booted ({names}). Say which one with --udid."
    return booted[0], None


def read_bundle(path):
    """Return (info, blocked message) for an .app folder."""
    app = pathlib.Path(path)
    if not app.is_dir() or app.suffix != ".app":
        return None, f"{path} is not an .app folder. Give the built bundle, for example .../Build/Products/Debug-iphonesimulator/Name.app."
    plist = app / "Info.plist"
    try:
        with plist.open("rb") as handle:
            info = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException, ValueError) as exc:
        return None, f"cannot read {plist}: {exc}"
    bundle_id, executable = info.get("CFBundleIdentifier"), info.get("CFBundleExecutable")
    if not bundle_id or not executable:
        return None, f"{plist} has no CFBundleIdentifier or no CFBundleExecutable; this is not a finished build."
    binary = app / executable
    if not binary.is_file():
        return None, f"the bundle names the executable {executable} but that file is not in the bundle."
    platforms = [str(p) for p in info.get("CFBundleSupportedPlatforms", [])] + [str(info.get("DTPlatformName", ""))]
    joined = " ".join(platforms).lower()
    if "iphoneos" in joined and "simulator" not in joined:
        return None, "this bundle was built for a device (iphoneos). A simulator needs a simulator build of the app."
    age = time.time() - binary.stat().st_mtime
    return {"path": str(app.resolve()), "bundle_id": bundle_id, "executable": executable,
            "version": info.get("CFBundleShortVersionString"), "build": info.get("CFBundleVersion"),
            "binary_age_minutes": round(age / 60, 1)}, None


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def judge_image(path):
    """Return (verdict, line, stats) using the thresholds file."""
    limits, notes = pngstat.load_limits()
    result = pngstat.stats(path, limits)
    verdict, line = pngstat.describe(result, limits)
    return verdict, line, result, notes


def cmd_devices(args):
    xcrun = find_xcrun(args.xcrun)
    if not xcrun:
        print(f"blocked: {GET_XCODE}")
        return 2
    devices, error = list_devices(xcrun)
    if error:
        print(f"RESULT not verified: {error}")
        return 2
    for d in sorted(devices, key=lambda d: (d["state"] != "Booted", d["runtime"], d["name"])):
        print(f"{d['state']:9} {d['runtime']:14} {d['name']:28} {d['udid']}{'' if d['available'] else '  (unavailable)'}")
    booted = [d for d in devices if d["state"] == "Booted"]
    print(f"checked: {len(devices)} simulators listed by simctl, {len(booted)} booted")
    if not booted:
        _, message = choose_device(devices, None)
        print(f"blocked: {message}")
        return 2
    print(f"RESULT pass: {len(booted)} booted simulator(s) found")
    return 0


def cmd_run(args):
    xcrun = find_xcrun(args.xcrun)
    if not xcrun:
        print(f"blocked: {GET_XCODE}")
        return 2
    bundle, message = read_bundle(args.app)
    if message:
        print(f"blocked: {message}")
        return 2
    try:
        pngstat.load_limits()
    except (OSError, ValueError) as exc:
        print(f"blocked: the thresholds file cannot be used ({exc})")
        return 2
    devices, error = list_devices(xcrun)
    if error:
        print(f"RESULT not verified: {error}")
        return 2
    device, message = choose_device(devices, args.udid)
    if message:
        print(f"blocked: {message}")
        return 2
    bundle_id = args.bundle_id or bundle["bundle_id"]
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = pathlib.Path(args.out) / stamp
    n = 1
    while out.exists():
        n += 1
        out = pathlib.Path(args.out) / f"{stamp}-{n}"
    out.mkdir(parents=True)
    state_root = pathlib.Path(args.out).parent
    if state_root.name == ".mstack":
        ignore = state_root / ".gitignore"
        have = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
        if "sim-proof/" not in have.split():
            ignore.write_text(have + ("" if have.endswith("\n") or not have else "\n") + "sim-proof/\n", encoding="utf-8")
    shot = out / "screen.png"
    record = {"screen": args.screen, "device": device, "app": bundle, "bundle_id": bundle_id,
              "started": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "steps": []}

    def finish(state, why, code):
        record["result"], record["reason"] = state, why
        (out / "record.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        print(f"record: {out / 'record.json'}")
        print(f"RESULT {state}" + (f": {why}" if why else ""))
        return code

    def step(name, ok, detail):
        record["steps"].append({"step": name, "ok": ok, "detail": detail})
        print(f"{'ok  ' if ok else 'FAIL'} {name}: {detail}")

    print(f"device: {device['name']} ({device['runtime']}) {device['udid']}")
    print(f"app: {bundle['path']} ({bundle_id}); the binary was written {bundle['binary_age_minutes']} minutes ago. "
          "If the source changed after that, build again first.")

    code, so, se = call([xcrun, "simctl", "install", device["udid"], bundle["path"]])
    if code != 0:
        step("install", False, f"simctl install ended with exit {code}")
        print(tail(se or so))
        return finish("fail", "the app did not install on the simulator", 1)
    step("install", True, "simctl install exit 0")

    code, so, se = call([xcrun, "simctl", "launch", "--terminate-running-process", device["udid"], bundle_id])
    found = re.search(r":\s*(\d+)\s*$", so.strip()) if code == 0 else None
    if not found:
        step("launch", False, f"simctl launch exit {code} and no process id in its output")
        print(tail(se or so))
        return finish("fail", "the app did not launch", 1)
    pid = int(found.group(1))
    record["pid"] = pid
    step("launch", True, f"process id {pid}")

    time.sleep(max(0.0, args.settle))
    if not alive(pid):
        step("still running", False, f"process {pid} ended within {args.settle} seconds of launch")
        return finish("fail", f"the app's process ended within {args.settle} seconds of launch; read the crash report (crash-read)", 1)
    step("still running", True, f"process {pid} alive {args.settle} seconds after launch")

    code, so, se = call([xcrun, "simctl", "io", device["udid"], "screenshot", "--type=png", str(shot)])
    if not shot.is_file() or shot.stat().st_size == 0:
        step("screenshot", False, f"simctl io screenshot exit {code}; no file at {shot}")
        print(tail(se or so))
        return finish("fail", "no screenshot was written", 1)
    step("screenshot", True, f"{shot} ({shot.stat().st_size} bytes)")

    verdict, line, stats, notes = judge_image(shot)
    record["image"] = {k: v for k, v in stats.items() if k != "file"}
    if notes:
        print("note: image thresholds are mstack defaults, not platform facts: " + "; ".join(notes))
    step("picture", verdict == "real", line.split(": ", 1)[-1])
    if verdict == "unknown":
        return finish("not verified", f"the screenshot could not be judged: {stats.get('error')}", 2)
    if verdict != "real":
        return finish("fail", f"the screenshot is {verdict}: {line.split(': ', 1)[-1]}", 1)
    if not alive(pid):
        step("still running after screenshot", False, f"process {pid} is gone")
        return finish("fail", "the app's process ended before the screenshot was checked; the picture may show the home screen", 1)
    step("still running after screenshot", True, f"process {pid} alive")
    print(f"screenshot: {shot}")
    print("not checked by this script: which screen the picture shows. Open the screenshot and compare it with the screen that was asked for"
          + (f" ({args.screen})." if args.screen else "."))
    return finish("pass", "", 0)


def cmd_check(args):
    path = pathlib.Path(args.image)
    try:
        verdict, line, stats, notes = judge_image(path)
    except (OSError, ValueError) as exc:
        print(f"blocked: the thresholds file cannot be used ({exc})")
        return 2
    if notes:
        print("note: image thresholds are mstack defaults, not platform facts: " + "; ".join(notes))
    print(line)
    if verdict in ("missing", "unknown"):
        print(f"RESULT not verified: {stats.get('error')}")
        return 2
    if verdict != "real":
        print(f"RESULT fail: the image is {verdict}: {line.split(': ', 1)[-1]}")
        return 1
    print("RESULT pass: the image is a readable picture that is not blank")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--xcrun", help="path of xcrun (default: the one on PATH)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("devices", help="list simulators and which are booted")
    run = sub.add_parser("run", help="install, launch, screenshot, check")
    run.add_argument("--app", required=True, help="path of the built .app bundle (a simulator build)")
    run.add_argument("--udid", help="simulator id; needed only when more than one is booted")
    run.add_argument("--bundle-id", help="bundle id to launch (default: read from the bundle's Info.plist)")
    run.add_argument("--screen", default="", help="name of the screen the user wants proved; kept in the record")
    run.add_argument("--settle", type=float, default=4.0, help="seconds to wait after launch before the first check (default 4)")
    run.add_argument("--out", default=".mstack/sim-proof", help="folder for the screenshot and record (default .mstack/sim-proof)")
    check = sub.add_parser("check", help="check one screenshot file")
    check.add_argument("image", help="PNG file")
    args = parser.parse_args()
    return {"devices": cmd_devices, "run": cmd_run, "check": cmd_check}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())

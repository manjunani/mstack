"""Test sim-proof's script without a simulator.

Usage: python3 sim_proof_cases.py <new folder under .testrun/>

No simulator is booted or touched. The `run` and `devices` paths are driven through a stand-in
for xcrun: a small program this test writes into the work folder, which answers `simctl list`,
`install`, `launch` and `io screenshot` the way the test case tells it to. That tests this
script's own logic (parsing, order of steps, what counts as failure). It does NOT test the real
simctl: whether a real launch prints its process id in the parsed form is not proven here.
One case calls the real xcrun on this machine, read-only (`simctl list devices --json`).
"""
import json
import os
import pathlib
import plistlib
import shutil
import subprocess
import sys

import fixtures as fx

W = fx.workdir(sys.argv)
SCRIPT = fx.SKILLS / "sim-proof" / "scripts" / "simproof.py"
PY = sys.executable
c = fx.Cases("sim-proof")

STUB = W / "fake-xcrun"
CONF = W / "fake-xcrun.json"
STUB.write_text(f"""#!{sys.executable}
import json, shutil, sys
conf = json.load(open({str(CONF)!r}))
a = sys.argv[1:]
log = open({str(W / 'calls.log')!r}, 'a'); log.write(' '.join(a) + chr(10)); log.close()
if a[:3] == ['simctl', 'list', 'devices']:
    sys.stdout.write(conf['listing']); sys.exit(conf.get('list_exit', 0))
if a[:2] == ['simctl', 'install']:
    sys.stderr.write(conf.get('install_err', '')); sys.exit(conf.get('install_exit', 0))
if a[:2] == ['simctl', 'launch']:
    sys.stdout.write(conf.get('launch_out', '')); sys.stderr.write(conf.get('launch_err', '')); sys.exit(conf.get('launch_exit', 0))
if a[:2] == ['simctl', 'io']:
    if conf.get('shot'):
        shutil.copyfile(conf['shot'], a[-1])
    sys.exit(conf.get('shot_exit', 0))
sys.exit(64)
""")
STUB.chmod(0o755)

UDID = "11111111-2222-3333-4444-555555555555"
OTHER = "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"


def listing(*states):
    devs = [{"udid": u, "name": n, "state": s, "isAvailable": True}
            for (u, n), s in zip(((UDID, "iPhone Test"), (OTHER, "iPad Test")), states)]
    return json.dumps({"devices": {"com.apple.CoreSimulator.SimRuntime.iOS-18-0": devs}})


def conf(**values):
    base = {"listing": listing("Booted", "Shutdown"), "launch_out": f"com.example.demo: {os.getpid()}\n"}
    base.update(values)
    CONF.write_text(json.dumps(base))


def make_app(name, platform="iphonesimulator", executable=True, bundle_id="com.example.demo"):
    app = W / name
    app.mkdir()
    info = {"CFBundleExecutable": "Demo", "CFBundleShortVersionString": "1.0", "CFBundleVersion": "1",
            "DTPlatformName": platform, "CFBundleSupportedPlatforms": ["iPhoneSimulator" if "sim" in platform else "iPhoneOS"]}
    if bundle_id:
        info["CFBundleIdentifier"] = bundle_id
    with (app / "Info.plist").open("wb") as handle:
        plistlib.dump(info, handle, fmt=plistlib.FMT_BINARY)
    if executable:
        (app / "Demo").write_bytes(b"\xcf\xfa\xed\xfe" + b"\0" * 64)
    return app


good = fx.write_png(W / "good.png", fx.picture(390, 844, seed=6), row_filter="mixed")
white = fx.write_png(W / "white.png", fx.flat(390, 844))
app = make_app("Demo.app")
proj = W / "project"
proj.mkdir()
base = [PY, SCRIPT, "--xcrun", STUB]

# check: image only
c.run(0, "check: a drawn screen passes", [PY, SCRIPT, "check", good])
c.run(1, "check: a white screen fails", [PY, SCRIPT, "check", white])
c.last_line("RESULT fail")
c.run(2, "check: a missing file is not verified", [PY, SCRIPT, "check", W / "none.png"])

# blocked paths
c.run(2, "no xcrun at the given path: blocked", [PY, SCRIPT, "--xcrun", W / "no-such-xcrun", "devices"])
c.last_line("blocked:")
c.has("Nothing was installed")
env = dict(os.environ, PATH="/var/empty")
c.run(2, "no xcrun on PATH: blocked", [PY, SCRIPT, "devices"], env=env)
c.last_line("blocked:")
conf(listing=listing("Shutdown", "Shutdown"))
c.run(2, "devices: none booted is blocked", base + ["devices"])
c.has("2 simulators exist but none is booted")
c.run(2, "run: none booted is blocked, nothing installed", base + ["run", "--app", app], cwd=proj)
c.true("install" not in (W / "calls.log").read_text(), "no install was attempted while blocked")
conf(listing=json.dumps({"devices": {}}))
c.run(2, "devices: no simulator at all is blocked", base + ["devices"])
c.has("No simulator exists")
conf(listing="Unable to locate device set")
c.run(2, "devices: output that is not JSON is not verified", base + ["devices"])
c.last_line("RESULT not verified")
conf(listing=listing("Booted", "Booted"))
c.run(2, "run: two booted and no --udid is blocked", base + ["run", "--app", app], cwd=proj)
c.has("Say which one with --udid")
conf()
c.run(2, "run: unknown --udid is blocked", base + ["run", "--app", app, "--udid", "NOPE"], cwd=proj)
c.run(2, "run: --udid of a shut-down simulator is blocked", base + ["run", "--app", app, "--udid", OTHER], cwd=proj)
c.run(2, "run: a device build is blocked", base + ["run", "--app", make_app("Device.app", platform="iphoneos")], cwd=proj)
c.has("built for a device")
c.run(2, "run: bundle without its executable is blocked", base + ["run", "--app", make_app("NoExe.app", executable=False)], cwd=proj)
c.run(2, "run: bundle without a bundle id is blocked", base + ["run", "--app", make_app("NoId.app", bundle_id=None)], cwd=proj)
c.run(2, "run: a path that is not an .app is blocked", base + ["run", "--app", W / "good.png"], cwd=proj)

# devices pass
conf()
c.run(0, "devices: one booted", base + ["devices"])
c.has("2 simulators listed by simctl, 1 booted")

# run: pass
conf(shot=str(good))
c.run(0, "run: install, launch, live process, real screenshot", base + ["run", "--app", app, "--screen", "Home", "--settle", "0.2"], cwd=proj)
c.last_line("RESULT pass")
c.has("not checked by this script: which screen")
records = sorted((proj / ".mstack" / "sim-proof").glob("*/record.json"))
c.true(len(records) == 1 and json.loads(records[0].read_text())["result"] == "pass", "a record with result pass was written under .mstack/sim-proof")
c.true((records[0].parent / "screen.png").read_bytes() == good.read_bytes(), "the screenshot is kept next to the record")
c.true("sim-proof/" in (proj / ".mstack" / ".gitignore").read_text(), ".mstack/.gitignore lists sim-proof/")
calls = (W / "calls.log").read_text()
c.true(f"simctl launch --terminate-running-process {UDID} com.example.demo" in calls, "launch used the bundle id read from Info.plist")

# run: failures
conf(shot=str(white))
c.run(1, "run: a white screenshot fails", base + ["run", "--app", app, "--settle", "0.2"], cwd=proj)
c.has("of the pixels are one colour")
conf(install_exit=1, install_err="An error was encountered processing the command\n")
c.run(1, "run: install failure fails", base + ["run", "--app", app, "--settle", "0.2"], cwd=proj)
c.has("did not install")
conf(launch_exit=4, launch_out="", launch_err="FBSOpenApplicationServiceErrorDomain\n")
c.run(1, "run: launch failure fails", base + ["run", "--app", app, "--settle", "0.2"], cwd=proj)
conf(launch_out="launched\n", shot=str(good))
c.run(1, "run: launch exit 0 but no process id fails", base + ["run", "--app", app, "--settle", "0.2"], cwd=proj)
gone = subprocess.Popen([PY, "-c", "pass"])
gone.wait()
conf(launch_out=f"com.example.demo: {gone.pid}\n", shot=str(good))
c.run(1, "run: process that ended after launch fails even with a good picture", base + ["run", "--app", app, "--settle", "0.2"], cwd=proj)
c.has("ended within")
conf(shot="", shot_exit=0)
c.run(1, "run: screenshot command exit 0 but no file fails", base + ["run", "--app", app, "--settle", "0.2"], cwd=proj)
c.has("no screenshot was written")
c.true(len(list((proj / ".mstack" / "sim-proof").glob("*/record.json"))) == 7, "every run wrote its own record folder (7 runs, none overwritten)")

# real xcrun, read-only
if shutil.which("xcrun"):
    done = c.run(0 if '"state" : "Booted"' in subprocess.run(["xcrun", "simctl", "list", "devices", "--json"], capture_output=True, text=True).stdout else 2,
                 "real xcrun: `devices` parses the real listing (exit follows whether one is booted)", [PY, SCRIPT, "devices"])
    c.has("simulators listed by simctl")
else:
    print("not run: xcrun is not on this machine")
c.run(0, "--help works", [PY, SCRIPT, "--help"])
sys.exit(c.finish())

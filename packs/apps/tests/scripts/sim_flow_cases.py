"""Test sim-flow's record checker. No simulator and no driving tool is used.

Usage: python3 sim_flow_cases.py <new folder under .testrun/>

The screenshots are PNG files this test draws. What is tested: which steps the script accepts,
which it refuses, and how `check` rolls the steps up. What is not tested: any real tapping.
"""
import json
import sys

import fixtures as fx

W = fx.workdir(sys.argv)
SCRIPT = fx.SKILLS / "sim-flow" / "scripts" / "flowcheck.py"
PY = sys.executable
c = fx.Cases("sim-flow")
shots = [fx.write_png(W / f"shot{n}.png", fx.picture(390, 844, seed=n), row_filter="mixed") for n in range(1, 5)]
white = fx.write_png(W / "white.png", fx.flat(390, 844))
proj = W / "project"
proj.mkdir()

c.run(2, "start with --driver none is blocked", [PY, SCRIPT, "start", "--name", "sign in", "--driver", "none"], cwd=proj)
c.last_line("blocked:")
c.has("cannot tap")
c.run(2, "start naming plain simctl as the driver is blocked", [PY, SCRIPT, "start", "--name", "sign in", "--driver", "simctl"], cwd=proj)
c.true(not (proj / ".mstack").exists(), "a blocked start writes nothing")
c.run(0, "start with a driver opens a record", [PY, SCRIPT, "start", "--name", "Sign in!", "--driver", "host simulator tool", "--app", "com.example.demo"], cwd=proj)
d = proj / ".mstack" / "sim-flow" / "sign-in"
c.true((d / "flow.json").is_file(), "record is at .mstack/sim-flow/sign-in/flow.json")
c.run(2, "start again with the same name refuses to overwrite", [PY, SCRIPT, "start", "--name", "sign in", "--driver", "x tool"], cwd=proj)
c.run(2, "check with no steps is not verified", [PY, SCRIPT, "check", d])
c.last_line("RESULT not verified")

step = [PY, SCRIPT, "step", "--dir", d]
c.run(2, "pass step without a screenshot is refused", step + ["--action", "launch", "--expected", "welcome screen", "--observed", "welcome", "--status", "pass"])
c.run(2, "pass step without an observation is refused", step + ["--action", "launch", "--expected", "welcome screen", "--screenshot", shots[0], "--status", "pass"])
c.run(2, "skipped step without a reason is refused", step + ["--action", "buy", "--expected", "receipt", "--status", "skipped"])
c.run(1, "step with a blank screenshot is not recorded", step + ["--action", "launch", "--expected", "welcome screen", "--observed", "white", "--screenshot", white, "--status", "pass"])
c.run(1, "step with a missing screenshot is not recorded", step + ["--action", "launch", "--expected", "welcome screen", "--observed", "x", "--screenshot", W / "gone.png", "--status", "pass"])
c.true(json.loads((d / "flow.json").read_text())["steps"] == [], "refused steps left the record empty")
c.run(0, "step 1 recorded", step + ["--action", "launch the app", "--expected", "welcome screen with a Sign in button", "--observed", "welcome screen, Sign in button visible", "--screenshot", shots[0], "--status", "pass"])
c.true((d / "01.png").read_bytes() == shots[0].read_bytes() and shots[0].exists(), "screenshot copied to 01.png, original left in place")
c.run(1, "step 2 with the same picture as step 1 is refused", step + ["--action", "tap Sign in", "--expected", "sign-in form", "--observed", "form", "--screenshot", shots[0], "--status", "pass"])
c.has("changed nothing on screen")
c.run(0, "step 2 recorded with a new picture", step + ["--action", "tap Sign in", "--expected", "sign-in form", "--observed", "form with email and password fields", "--screenshot", shots[1], "--status", "pass"])
c.run(0, "step 3 recorded with --same-screen and the same picture", step + ["--action", "tap outside the form", "--expected", "form stays open", "--observed", "form still open", "--screenshot", shots[1], "--status", "pass", "--same-screen"])
c.run(0, "check: three passed steps pass", [PY, SCRIPT, "check", d])
c.last_line("RESULT pass: 3 of 3")
c.run(0, "check accepts the flow.json path too", [PY, SCRIPT, "check", d / "flow.json"])

c.run(0, "step 4 left to a person", step + ["--action", "Sign in with Apple", "--expected", "signed-in home screen", "--status", "human", "--reason", "needs a real Apple account"])
c.run(2, "check: a step left to a person makes the flow not verified", [PY, SCRIPT, "check", d])
c.has("needs a real Apple account")
c.run(0, "step 5 recorded as fail", step + ["--action", "tap Continue", "--expected", "home screen", "--observed", "error banner: network unavailable", "--screenshot", shots[2], "--status", "fail"])
c.run(1, "check: a failed step fails the flow, ahead of not verified", [PY, SCRIPT, "check", d])
c.has("RESULT fail: step 5 failed")
c.has("observed: error banner")

# records damaged or written by hand
def variant(name, change):
    folder = W / name
    folder.mkdir()
    for f in d.iterdir():
        (folder / f.name).write_bytes(f.read_bytes())
    data = json.loads((folder / "flow.json").read_text())
    data["steps"] = data["steps"][:3]
    change(data, folder)
    (folder / "flow.json").write_text(json.dumps(data))
    return folder


c.run(0, "copy of the first three steps passes", [PY, SCRIPT, "check", variant("v-ok", lambda data, f: None)])
c.run(1, "screenshot replaced by a blank one after recording", [PY, SCRIPT, "check", variant("v-blank", lambda data, f: (f / "02.png").write_bytes(white.read_bytes()))])
c.has("02.png is blank")
c.run(1, "screenshot replaced by another real picture after recording", [PY, SCRIPT, "check", variant("v-swap", lambda data, f: (f / "02.png").write_bytes(shots[3].read_bytes()))])
c.has("changed after it was recorded")
c.run(1, "screenshot file deleted from the record", [PY, SCRIPT, "check", variant("v-gone", lambda data, f: data["steps"][1].update(screenshot="missing.png"))])
c.run(1, "step with an empty expected screen", [PY, SCRIPT, "check", variant("v-noexp", lambda data, f: data["steps"][0].update(expected=""))])
c.has("no expected")
c.run(1, "step with an unknown status", [PY, SCRIPT, "check", variant("v-status", lambda data, f: data["steps"][0].update(status="done"))])
c.run(1, "hand-written record reusing one screenshot for two passed steps",
      [PY, SCRIPT, "check", variant("v-reuse", lambda data, f: [s.pop("sha256", None) for s in data["steps"]] and data["steps"][1].update(screenshot="01.png"))])
c.has("identical to step 1")
c.run(2, "record whose driver is 'none' is blocked", [PY, SCRIPT, "check", variant("v-nodriver", lambda data, f: data.update(driver="none"))])
(W / "broken").mkdir()
(W / "broken" / "flow.json").write_text("{not json")
c.run(2, "record that is not JSON is blocked", [PY, SCRIPT, "check", W / "broken"])
c.run(2, "folder with no record is blocked", [PY, SCRIPT, "check", W])
c.run(0, "--help works", [PY, SCRIPT, "--help"])
sys.exit(c.finish())

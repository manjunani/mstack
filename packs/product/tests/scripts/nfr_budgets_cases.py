"""Run nfr-budgets' budgets.py on a throwaway project whose check commands are small local scripts.

The refused-command sample is text written to a file. It is never run; the test checks that it is not.
Usage: nfr_budgets_cases.py <path to budgets.py> <new folder>
"""
import argparse
import copy
import json

import casekit

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("script")
parser.add_argument("folder")
args = parser.parse_args()
c = casekit.Cases(args.script, args.folder, "nfr-budgets")

c.write("tools/size.py", "print('bundle: 1200 bytes')\n")
c.write("tools/slow.py", "import time\ntime.sleep(0.2)\nprint('done')\n")
c.write("tools/audit.py", "import sys\nsys.exit(0)\n")
c.write("tools/audit_bad.py", "import sys\nprint('2 high advisories')\nsys.exit(1)\n")
c.write("tools/quiet.py", "print('all good')\n")
c.write("tools/coverage.py", "print('TOTAL 85')\n")
c.write("tools/count.py", "import sys\nprint(len(sys.stdin.read().splitlines()))\n")
c.write("tools/marker.py", "import pathlib\npathlib.Path('marker.txt').write_text('ran')\nprint(1)\n")

SIZE = {"id": "B-01", "quality": "fast", "metric": "bundle size", "number": 2000, "unit": "bytes", "direction": "at most",
        "condition": "production build", "check": "python3 tools/size.py", "measure": "output"}
SLOW = {"id": "B-02", "quality": "fast", "metric": "export time", "number": 5000, "unit": "ms",
        "condition": "10,000 rows on a laptop", "check": "python3 tools/slow.py", "measure": "duration"}
AUDIT = {"id": "B-03", "quality": "secure", "metric": "audit exit code", "number": 0, "unit": "exit code",
         "condition": "high severity only", "check": "python3 tools/audit.py", "measure": "exit"}
COVER = {"id": "B-04", "quality": "reliable", "metric": "line coverage", "number": 80, "unit": "%", "direction": "at least",
         "condition": "unit tests only", "check": "python3 tools/coverage.py", "measure": "output"}


def project(name, budgets):
    c.write(f"{name}/.mstack/budgets.json", {"budgets": budgets})
    for tool in (c.folder / "tools").iterdir():
        c.write(f"{name}/tools/{tool.name}", tool.read_text(encoding="utf-8"))
    return name


def changed(budget, **fields):
    new = copy.deepcopy(budget)
    for key, value in fields.items():
        if value is None:
            new.pop(key, None)
        else:
            new[key] = value
    return new


c.run("no budgets file is blocked", 2, "--root", ".", "list", expect="does not exist")
c.run("template writes a skeleton", 0, "--root", "skel", "template")
c.run("template refuses to overwrite", 2, "--root", "skel", "template", expect="not overwritten")
c.run("the untouched skeleton is refused", 2, "--root", "skel", "baseline", expect="lacks metric, unit, condition, check")

good = project("good", [SIZE, SLOW, AUDIT, COVER])
before = (c.folder / good / ".mstack" / "budgets.json").read_text(encoding="utf-8")
c.run("list prints the commands", 0, "--root", good, "list", expect="runs: python3 tools/slow.py")
c.run("check with no baseline is refused: a number set without measuring", 2, "--root", good, "check", expect="set with no baseline")
out = c.run("baseline records the current values", 0, "--root", good, "baseline", "--runs", "3", expect="bundle size: 1200 bytes now")
c.check("baseline shows three runs for the timed command", out.count(",") >= 2 and "runs:" in out)
base = json.loads((c.folder / good / ".mstack" / "budgets-baseline.json").read_text(encoding="utf-8"))
c.check("the baseline file holds the measured size, not the limit", base["B-01"]["value"] == 1200.0)
c.check("the timed baseline is at least the 200 ms the command sleeps", base["B-02"]["value"] >= 200)
out = c.run("all four budgets pass", 0, "--root", good, "check", expect="RESULT pass")
c.check("an 'at least' budget passes when the value is above the number", "B-04   pass" in out)
c.check("the budgets file was not changed by baseline or check", (c.folder / good / ".mstack" / "budgets.json").read_text(encoding="utf-8") == before)
c.check("the last-run record is git-ignored", "budgets-last.json" in (c.folder / good / ".mstack" / ".gitignore").read_text(encoding="utf-8"))
c.run("one budget can be run by id", 0, "--root", good, "check", "B-01", expect="1 budgets run")
c.run("an unknown id is blocked", 2, "--root", good, "check", "B-77", expect="no such budget")

over = project("over", [changed(SIZE, number=1000), changed(SLOW, number=50), changed(AUDIT, check="python3 tools/audit_bad.py"), changed(COVER, number=90)])
c.run("baseline for the failing project", 0, "--root", over, "baseline")
out = c.run("values outside their numbers fail", 1, "--root", over, "check", expect="RESULT fail: over budget: B-01, B-02, B-03, B-04")
c.check("the failing line shows value, limit and baseline", "1200 bytes (limit: at most 1000 bytes; baseline 1200" in out)

for field in ("metric", "number", "unit", "condition", "check"):
    lacking = project(f"no-{field}", [changed(SIZE, **{field: None})])
    c.run(f"a budget with no {field} is refused by check", 2, "--root", lacking, "check", expect=f"lacks {field}")
c.run("a number that is a word is refused", 2, "--root", project("word", [changed(SIZE, number="fast")]), "check", expect="lacks number")
c.run("a placeholder condition is refused", 2, "--root", project("tbd", [changed(SIZE, condition="TBD")]), "check", expect="lacks condition")
c.run("a duration in minutes is refused", 2, "--root", project("minutes", [changed(SLOW, unit="minutes")]), "baseline", expect="reported in s or ms")
c.run("an unknown way of measuring is refused", 2, "--root", project("how", [changed(SIZE, measure="feeling")]), "baseline", expect="measure must be one of")
c.run("a baseline may be taken before the number is set", 0, "--root", project("nonumber", [changed(SIZE, number=None)]), "baseline", expect="1200 bytes now")
c.run("and check then refuses the budget that still has no number", 2, "--root", "nonumber", "check", expect="lacks number")

moved = project("moved", [SIZE])
c.run("baseline, then the command changes", 0, "--root", moved, "baseline")
c.write("moved/.mstack/budgets.json", {"budgets": [changed(SIZE, check="python3 tools/coverage.py")]})
c.run("a changed check command voids the baseline", 2, "--root", moved, "check", expect="changed since the baseline")

unread = project("unread", [changed(SIZE, check="python3 tools/quiet.py"), changed(SLOW, id="B-02", check="python3 tools/audit_bad.py", unit="s"),
                            changed(COVER, id="B-03", check="mstack-no-such-tool --version"),
                            changed(COVER, id="B-04", check="mstack-no-such-tool | python3 tools/count.py", direction="at most", number=5),
                            changed(COVER, id="B-05", check="python3 tools/audit_bad.py | python3 tools/count.py", direction="at most", number=5)])
out = c.run("values that cannot be read give no baseline", 2, "--root", unread, "baseline", expect="RESULT not verified")
c.check("a command that prints no number is named", "B-01  not measured: the command printed no number" in out)
c.check("timing a failing command is not accepted", "B-02  not measured: the command exited 1" in out)
c.check("a missing tool is named", "tool not found: mstack-no-such-tool" in out)
c.check("a missing tool at the start of a pipe is not read as the value 0", "B-04  not measured" in out)
c.check("a tool that fails in the middle of a pipe is not hidden by the last command's exit 0", "B-05  not measured: the command exited 1" in out)

flip = project("flip", [changed(SIZE, check="python3 tools/size.py"), COVER])
c.run("baseline while everything can be read", 0, "--root", flip, "baseline")
c.write("flip/tools/coverage.py", "print('no data')\n")
c.run("a value that stops being readable is not verified, never a pass", 2, "--root", flip, "check", expect="RESULT not verified: B-04")
c.write("flip/tools/size.py", "print('bundle: 9999 bytes')\n")
c.run("a failure outranks a not-verified value", 1, "--root", flip, "check", expect="RESULT fail: over budget: B-01")

refused_command = "r" + "m -r" + "f build && python3 tools/marker.py"
risky = project("risky", [changed(SIZE, check=refused_command), changed(COVER, id="B-02", check="python3 tools/marker.py")])
c.run("a check command that deletes is refused and nothing runs", 2, "--root", risky, "baseline", expect="is refused because it can delete")
c.check("no command of the refused file was run", not (c.folder / risky / "marker.txt").exists())
c.run("list also shows the refusal, and runs nothing", 2, "--root", risky, "list", expect="REFUSED")
c.check("list ran nothing", not (c.folder / risky / "marker.txt").exists())
c.write("broken/.mstack/budgets.json", "{ not json")
c.run("a file that is not JSON is blocked", 2, "--root", "broken", "check", expect="must be JSON")
c.done()

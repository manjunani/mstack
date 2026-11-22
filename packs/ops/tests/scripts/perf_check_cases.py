"""Run perf-check's measure.py on a small program whose running time this test controls.

The program sleeps for the next duration in durations.txt, so a "change" is made by rewriting that file.
Usage: perf_check_cases.py <new empty folder>
"""
import argparse
import json
import sys

import harness

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("folder")
folder = harness.new_folder(parser.parse_args().folder)
tool = harness.script("perf-check", "measure.py")
cases = harness.Cases("perf-check")

(folder / "work.py").write_text(
    "import pathlib, sys, time\n"
    "here = pathlib.Path(__file__).parent\n"
    "plan = [float(x) for x in (here / 'durations.txt').read_text().split()]\n"
    "count = here / 'count.txt'\n"
    "n = int(count.read_text()) if count.exists() else 0\n"
    "count.write_text(str(n + 1))\n"
    "if plan[n % len(plan)] < 0:\n    print('boom: negative duration'); sys.exit(3)\n"
    "time.sleep(plan[n % len(plan)])\n", encoding="utf-8")


def plan(*seconds):
    (folder / "durations.txt").write_text(" ".join(str(s) for s in seconds), encoding="utf-8")
    (folder / "count.txt").write_text("0", encoding="utf-8")


def timed(durations, want, *args):
    """Timing cases depend on machine load. Retry up to 3 times; the attempt count is printed so a flaky pass shows."""
    for attempt in range(1, 4):
        plan(*durations)
        code, out = harness.run(tool, *args)
        if code == want:
            break
    if attempt > 1:
        print(f"     (needed {attempt} attempts: the machine was busy)")
    return code, out


base = ("--root", folder)
cmd = ("--", sys.executable, "work.py")
steady = (0.60, 0.66, 0.54, 0.63, 0.57)  # long enough that process start-up jitter stays inside the spread

code, out = timed((*steady,), 2, *base, "compare", "--name", "job")
cases.check("compare before any baseline", code, 2, out, last="blocked")
code, out = harness.run(tool, *base, "baseline", "--name", "job", "--runs", "3", *cmd)
cases.check("too few runs", code, 2, out, last="blocked")
code, out = timed(steady, 0, *base, "baseline", "--name", "job", "--runs", "5", "--warmup", "0", "--replace", *cmd)
cases.check("baseline taken", code, 0, out, has=("run 5:", "unverified defaults"), lacks=("warm-up:",), last="RESULT pass")
saved = json.loads((folder / ".mstack/perf-check/job.json").read_text())
cases.check("baseline file holds 5 times and a median near 600 ms plus start-up", 0 if len(saved["times_ms"]) == 5 and 600 < saved["median"] < 1100 else 1, 0, str(saved["median"]))

code, out = timed((*steady,), 2, *base, "compare", "--name", "job")
cases.check("no real change: inside the noise", code, 2, out, has=("inside the noise",), last="RESULT not verified")
code, out = timed((*steady,), 0, *base, "compare", "--name", "job", "--goal", "not-slower")
cases.check("no real change, goal not-slower", code, 0, out, last="RESULT pass: no change beyond noise")

code, out = timed((*(s + 0.9 for s in steady),), 1, *base, "compare", "--name", "job")
cases.check("900 ms slower", code, 1, out, has=("Revert the change",), last="RESULT fail: slower")
last = json.loads((folder / ".mstack/perf-check/job.last.json").read_text())
cases.check("comparison record says about +900 ms", 0 if 700 < last["difference_ms"] < 1150 and last["state"] == "fail" else 1, 0, str(last["difference_ms"]))

code, out = timed((0.18, 0.21, 0.15, 0.20, 0.16,), 0, *base, "compare", "--name", "job")
cases.check("420 ms faster", code, 0, out, has=("Keep the change",), last="RESULT pass: faster")

code, out = timed((0.03, 1.2, 0.06, 1.0, 0.03,), 2, *base, "compare", "--name", "job")
cases.check("timings vary too much to tell", code, 2, out, has=("vary too much",), last="RESULT not verified")
code, out = timed((0.03, 1.2, 0.06, 1.0, 0.03,), 2, *base, "baseline", "--name", "noisy", "--runs", "5", "--warmup", "0", *cmd)
cases.check("noisy baseline is saved but not verified", code, 2, out, has=("saved:",), last="RESULT not verified")

plan(*steady)
code, out = harness.run(tool, *base, "baseline", "--name", "job", "--runs", "5", *cmd)
cases.check("existing baseline is not overwritten", code, 2, out, last="blocked")
code, out = timed(steady, 0, *base, "baseline", "--name", "job", "--runs", "5", "--replace", *cmd)
olds = list((folder / ".mstack/perf-check").glob("job.*.old.json"))
cases.check("--replace keeps the earlier baseline aside", code, 0, out, has=("warm-up:", "kept as"), last="RESULT pass")
cases.check("the earlier baseline was kept, not deleted", 0 if len(olds) >= 1 else 1, 0)

plan(0.01, -1)
code, out = harness.run(tool, *base, "baseline", "--name", "broken", "--runs", "5", "--warmup", "0", *cmd)
cases.check("command that fails is not measured", code, 2, out, has=("exited 3 on run 2", "| boom"), last="blocked")
cases.check("no baseline saved for the failing command", 1 if (folder / ".mstack/perf-check/broken.json").exists() else 0, 0)
code, out = harness.run(tool, *base, "baseline", "--name", "ghost", "--runs", "5", "--", "no-such-program-mstack")
cases.check("command not found", code, 2, out, last="blocked")
code, out = harness.run(tool, *base, "baseline", "--name", "../escape", "--runs", "5", *cmd)
cases.check("name that would leave the folder", code, 2, out, last="blocked")
code, out = harness.run(tool, *base, "show", "--name", "job")
cases.check("show prints the baseline", code, 0, out, has=('"times_ms"',))

raise SystemExit(cases.finish())

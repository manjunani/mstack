"""Run rollback's rollback.py against a web server on 127.0.0.1 whose "deployed" version is a text file.

The rollback command used here is a small local program that rewrites that file. No real service is touched.
Usage: rollback_cases.py <new empty folder>
"""
import argparse
import json
import shlex
import sys

import harness
import localsite

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("folder")
folder = harness.new_folder(parser.parse_args().folder)
tool = harness.script("rollback", "rollback.py")
cases = harness.Cases("rollback")
version = folder / "version.txt"
version.write_text("v2-bad\n", encoding="utf-8")
server, base = localsite.start(version)
r = ("--root", folder)
(folder / "switch.py").write_text("import pathlib, sys\npathlib.Path(sys.argv[2]).write_text(sys.argv[1] + '\\n')\nprint('switched to', sys.argv[1])\n", encoding="utf-8")
(folder / "broken.py").write_text("import sys\nprint('platform said no')\nsys.exit(4)\n", encoding="utf-8")
switch = f"{shlex.quote(sys.executable)} switch.py v1-good {shlex.quote(str(version))}"
full = ("--previous", "v1-good", "--current", "v2-bad", "--command", switch, "--check-url", base + "/health")

code, out = harness.run(tool, *r, "plan")
cases.check("empty plan lists all four parts", code, 2, out, has=("previous:", "command:", "data:", "check:"), last="blocked")
code, out = harness.run(tool, *r, "plan", *full, "--data", "unknown")
cases.check("data compatibility unknown", code, 2, out, has=("Find out first",), last="blocked")
code, out = harness.run(tool, *r, "plan", *full, "--data", "incompatible")
cases.check("data incompatible", code, 2, out, has=("old code on changed data",), last="blocked")
code, out = harness.run(tool, *r, "plan", *full, "--data", "compatible")
cases.check("compatible without a reason", code, 2, out, has=("data reason",), last="blocked")
code, out = harness.run(tool, *r, "plan", "--previous", "v2-bad", "--current", "v2-bad", "--command", switch, "--data", "compatible",
                        "--data-reason", "no migrations", "--check-url", base + "/health")
cases.check("previous equals current", code, 2, out, has=("changes nothing",), last="blocked")
code, out = harness.run(tool, *r, "plan", "--previous", "v1-good", "--command", switch + " ; echo done", "--data", "compatible",
                        "--data-reason", "no migrations", "--check-url", base + "/health")
cases.check("chained command is refused", code, 2, out, has=("one command",), last="blocked")
code, out = harness.run(tool, *r, "plan", "--previous", "v1-good", "--command", "deploy-tool redeploy --latest-but-one", "--data", "compatible",
                        "--data-reason", "no migrations", "--check-url", base + "/health")
cases.check("command that does not name the version gets a note", code, 0, out, has=("does not name 'v1-good'",))

code, out = harness.run(tool, *r, "apply")
cases.check("apply on a complete plan without --execute prints the command only", code, 2, out, has=("would run: deploy-tool",), last="blocked")

code, out = harness.run(tool, *r, "plan", *full, "--data", "compatible", "--data-reason", "no migration ran since v1-good")
cases.check("complete plan", code, 0, out, lacks=("note:",), last="RESULT pass: the plan is complete. Nothing was run.")
code, out = harness.run(tool, *r, "confirm", "--repeat", "2", "--interval", "0")
cases.check("confirm before the rollback: the bad version still serves", code, 1, out, has=("version NOT found",), last="RESULT fail")
code, out = harness.run(tool, *r, "apply")
cases.check("apply without --execute runs nothing", code, 2, out, last="blocked")
cases.check("the version file is unchanged", 0 if version.read_text().strip() == "v2-bad" else 1, 0)
code, out = harness.run(tool, *r, "apply", "--execute")
cases.check("apply --execute runs the command", code, 0, out, has=("switched to v1-good",), last="RESULT pass: the command exited 0")
code, out = harness.run(tool, *r, "confirm", "--repeat", "3", "--interval", "0")
cases.check("confirm: the previous version is serving", code, 0, out, last="RESULT pass: the previous version 'v1-good' is serving")
plan = json.loads((folder / ".mstack/rollback/plan.json").read_text())
cases.check("plan records apply and confirm", 0 if plan["applied"]["exit"] == 0 and plan["confirmed"]["state"] == "pass" else 1, 0)

code, out = harness.run(tool, *r, "plan", "--previous", "v1-good", "--command", f"{shlex.quote(sys.executable)} broken.py v1-good",
                        "--data", "compatible", "--data-reason", "no migrations", "--check-url", base + "/health")
code, out = harness.run(tool, *r, "apply", "--execute")
cases.check("rollback command that fails", code, 1, out, has=("platform said no",), last="RESULT fail: the rollback command exited 4")
code, out = harness.run(tool, *r, "plan", "--previous", "v1-good", "--command", "no-such-tool-mstack v1-good",
                        "--data", "compatible", "--data-reason", "no migrations", "--check-url", base + "/health")
code, out = harness.run(tool, *r, "apply", "--execute")
cases.check("rollback tool not installed", code, 2, out, last="blocked")
code, out = harness.run(tool, *r, "plan", "--previous", "v1-good", "--command", switch, "--data", "compatible",
                        "--data-reason", "x", "--check-url", "ftp://example.invalid/")
cases.check("check address that is not http", code, 2, out, last="blocked")
code, out = harness.run(tool, "--root", folder / "fresh", "confirm")
cases.check("confirm with no plan", code, 2, out, last="blocked")

server.shutdown()
raise SystemExit(cases.finish())

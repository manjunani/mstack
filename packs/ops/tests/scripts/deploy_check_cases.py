"""Run deploy-check's probe.py against a web server started on 127.0.0.1 by this test.

Usage: deploy_check_cases.py <new empty folder>
"""
import argparse
import json
import socket

import harness
import localsite

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("folder")
folder = harness.new_folder(parser.parse_args().folder)
probe = harness.script("deploy-check", "probe.py")
version = folder / "version.txt"
version.write_text("abc1234\n", encoding="utf-8")
server, base = localsite.start(version)
fast = ("--repeat", "2", "--interval", "0", "--root", folder)
cases = harness.Cases("deploy-check")

code, out = harness.run(probe, base + "/health", "--expect", "abc1234", *fast)
cases.check("expected version is live", code, 0, out, has=("version found in header X-Version",), last="RESULT pass")
record = json.loads((folder / ".mstack/deploy-check/last.json").read_text())
cases.check("record written with 2 attempts", 0 if len(record["attempts"]) == 2 and record["state"] == "pass" else 1, 0)

code, out = harness.run(probe, base + "/health", "--expect", "abc1234", "--header", "Etag", *fast)
cases.check("version asked for in a header that lacks it", code, 1, out, last="RESULT fail")

code, out = harness.run(probe, base + "/health", "--expect", "fff9999", *fast)
cases.check("an older version is still live", code, 1, out, has=("version NOT found",), last="RESULT fail")

code, out = harness.run(probe, base + "/health", *fast)
cases.check("healthy but no expected version given", code, 2, out, last="RESULT not verified")

code, out = harness.run(probe, base + "/broken", "--expect", "abc1234", *fast)
cases.check("status 500", code, 1, out, has=("status 500, expected 200",), last="RESULT fail")

code, out = harness.run(probe, base + "/slow", "--expect", "abc1234", "--max-ms", "150", *fast)
cases.check("median over the time limit", code, 1, out, has=("over the limit",), last="RESULT fail")

code, out = harness.run(probe, base + "/slow", "--expect", "abc1234", "--max-ms", "3000", *fast)
cases.check("slow address inside a wider limit", code, 0, out, last="RESULT pass")

code, out = harness.run(probe, base + "/empty", "--expect", "abc1234", *fast)
cases.check("empty body", code, 1, out, has=("the body is empty",), last="RESULT fail")

code, out = harness.run(probe, base + "/moved", "--expect", "abc1234", *fast)
cases.check("redirect is reported, not followed", code, 1, out, has=("redirects to /health", "status 302"), last="RESULT fail")

code, out = harness.run(probe, base + "/health", "--expect", "abc1234", "--repeat", "1", "--no-record", "--root", folder / "nowhere")
cases.check("default limit prints the unverified note", code, 0, out, has=("unverified default",))
cases.check("--no-record writes nothing", 1 if (folder / "nowhere").exists() else 0, 0)

with socket.socket() as sock:  # a port that is free and has no listener
    sock.bind(("127.0.0.1", 0))
    dead = sock.getsockname()[1]
code, out = harness.run(probe, f"http://127.0.0.1:{dead}/health", "--expect", "abc1234", "--timeout", "2", *fast)
cases.check("nothing listening", code, 1, out, has=("no answer",), last="RESULT fail")

code, out = harness.run(probe, "ftp://example.invalid/x", "--no-record")
cases.check("not an http address", code, 2, out, last="blocked")
code, out = harness.run(probe, "https://user:pw@example.invalid/x", "--no-record")
cases.check("address with credentials is refused", code, 2, out, last="blocked", lacks=("pw@",))

server.shutdown()
raise SystemExit(cases.finish())

"""Script test for usage-report: made-up transcripts for two projects with known totals.

shop, session s1 (today): turn a 100 in / 10 out / 1,000 read / 200 write = 1,310
                          turn b written over two lines (output 5 then 20), counted once: 50 / 20 / 2,000 / 0 = 2,070
shop, subagent of s1 (today): 10 / 5 / 0 / 0 = 15, counted under shop and session s1
blog, session s2 (yesterday): 300 / 30 / 0 / 3,000 = 3,330
blog, session s3 (2001, outside any normal period): 999 / 0 / 0 / 0
Totals for 30 days: shop 3,395; blog 3,330; all 6,725. Cache reads 3,000 of input-side 6,660 = 45%.

Usage: usage_report_cases.py <folder>   (a new run folder is made inside it, for example .testrun/lean-usage-report)
"""
import argparse
import datetime
import sys

import casekit

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("folder")
args = parser.parse_args()
t = casekit.Cases("usage-report cases", args.folder)
USAGE = casekit.SKILLS / "usage-report" / "scripts" / "usage.py"
turn, user = casekit.turn, casekit.user

today = datetime.date.today()
T = f"{today.isoformat()}T09:00:00Z"
Y = f"{(today - datetime.timedelta(days=1)).isoformat()}T09:00:00Z"
OLD = "2001-01-01T00:00:00Z"
t.jsonl("projects/-work-shop/s1.jsonl", [user(ts=T), turn("a", 100, 1000, 200, 10, ts=T),
                                         turn("b", 50, 2000, 0, 5, ts=T), turn("b", 50, 2000, 0, 20, ts=T), "not json"])
t.jsonl("projects/-work-shop/s1/subagents/agent-1.jsonl", [turn("c", 10, 0, 0, 5, ts=T)])
t.jsonl("projects/-work-blog/s2.jsonl", [user(ts=Y, cwd="/work/blog"), turn("d", 300, 0, 3000, 30, ts=Y, cwd="/work/blog")])
t.jsonl("projects/-work-blog/s3.jsonl", [turn("e", 999, 0, 0, 0, ts=OLD, cwd="/work/blog")])
P = ["--projects-dir", t.root / "projects"]

out = t.run("tables per project, per day and top sessions", USAGE, P, 0, contains=[
    "4 transcripts read, 1 lines not readable",
    "  shop                                    160             35          3,000            200          3,395",
    "  blog                                    300             30              0          3,000          3,330",
    f"{today.isoformat()}", "shop s1", "blog s2",
    "total 6,725 tokens; cache reads are 45% of input-side tokens",
    "RESULT pass: 6,725 tokens over 2 projects and 2 sessions"], absent=["999", "made-up"])
t.run("one project only", USAGE, [*P, "--project-name", "blog"], 0, contains=["total 3,330 tokens"], absent=["shop"])
t.run("a one-day period leaves out yesterday", USAGE, [*P, "--days", "1"], 0, contains=["total 3,395 tokens"])
t.run("over a limit fails", USAGE, [*P, "--limit", "5000"], 1, contains=["6,725 tokens in the period, over the limit of 5,000"])
t.run("within a limit passes", USAGE, [*P, "--limit", "10000"], 0, contains=["within the limit of 10,000"])
t.run("--top limits the session list", USAGE, [*P, "--top", "1"], 0, contains=["top 1 sessions"], absent=["blog s2"])
t.run("a project with no usage in the period is not verified", USAGE, [*P, "--project-name", "nothing"], 2,
      contains=["RESULT not verified: no usage fields"])
t.run("a missing folder is blocked", USAGE, ["--projects-dir", t.root / "nope"], 2, contains=["RESULT blocked"])
t.run("a bad period is blocked", USAGE, [*P, "--days", "0"], 2, contains=["RESULT blocked"])
sys.exit(t.done())

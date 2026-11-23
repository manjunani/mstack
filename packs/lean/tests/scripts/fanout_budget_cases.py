"""Script test for fanout-budget: made-up subagent transcripts with known totals.

Past runs of the project (timestamps in 2000, before any budget is set):
  r1 10,000   r2 20,000   r3 30,000 (one reply over two lines, counted once)   r4 40,000   r5 100,000
  median 30,000; 90th percentile 100,000 (index round(0.9 x 4) = 4)
Runs after the budget is set carry a timestamp in 2999 so they always count as "since".

Usage: fanout_budget_cases.py <folder>   (a new run folder is made inside it, for example .testrun/lean-fanout-budget)
"""
import argparse
import json
import sys

import casekit

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("folder")
args = parser.parse_args()
t = casekit.Cases("fanout-budget cases", args.folder)
BUDGET = casekit.SKILLS / "fanout-budget" / "scripts" / "budget.py"
turn = casekit.turn

project = t.root / "work" / "shop"
project.mkdir(parents=True)
pdir = t.root / "projects"
sess = f"projects/{casekit.slug(project)}/sess-1/subagents"
OLD = "2000-01-01T00:00:00Z"
t.jsonl(f"{sess}/agent-r1.jsonl", [turn("a", 6000, 2000, 1000, 1000, ts=OLD)])
t.jsonl(f"{sess}/agent-r2.jsonl", [turn("b", 10000, 0, 0, 0, ts=OLD), turn("c", 0, 9000, 0, 1000, ts=OLD)])
t.jsonl(f"{sess}/agent-r3.jsonl", [turn("d", 29000, 0, 0, 500, ts=OLD), turn("d", 29000, 0, 0, 1000, ts=OLD)])
t.jsonl(f"{sess}/agent-r4.jsonl", [turn("e", 40000, 0, 0, 0, ts=OLD)])
t.jsonl(f"{sess}/agent-r5.jsonl", [turn("f", 90000, 0, 0, 10000, ts=OLD)])
t.jsonl(f"{sess}/agent-empty.jsonl", ["not json"])
t.jsonl("projects/other-project/s/subagents/agent-x.jsonl", [turn("g", 7, 0, 0, 0, ts=OLD)])
P = ["--project", project, "--projects-dir", pdir]

t.run("estimate from past runs", BUDGET, ["estimate", *P, "--launches", "4"], 0,
      contains=["past subagent runs: 5", "median 30,000", "90th percentile 100,000", "largest 100,000",
                "4 launches: about 400,000 tokens (median-based: 120,000)"])
t.run("estimate with a given per-run figure", BUDGET, ["estimate", *P, "--launches", "3", "--per-run", "5000"], 0,
      contains=["per run used: 5,000 (given with --per-run)", "about 15,000 tokens"])
t.run("--all-projects reads every project", BUDGET, ["estimate", *P, "--all-projects"], 0, contains=["past subagent runs: 6"])
empty = t.root / "work" / "new"
empty.mkdir()
t.run("no past runs and no figure is blocked", BUDGET, ["estimate", "--project", empty, "--projects-dir", pdir], 2,
      contains=["RESULT blocked: no past runs"])
t.run("check with no budget file is blocked", BUDGET, ["check", *P], 2, contains=["run 'budget.py set --limit <tokens>' first"])
t.run("set without a limit is blocked", BUDGET, ["set", *P], 2, contains=["set needs --limit"])
t.check("nothing written when set is blocked", not (project / ".mstack").exists())

t.run("set writes the budget file", BUDGET, ["set", *P, "--limit", "350000"], 0,
      contains=["limit 350,000 tokens, 100,000 per run", "room for about 3 runs"])
budget_file = project / ".mstack" / "fanout-budget.json"
t.check("the budget file is the only file written", sorted(p.name for p in (project / ".mstack").iterdir()) == ["fanout-budget.json"])
t.run("old runs do not count against a new budget", BUDGET, ["check", *P, "--launches", "3"], 0,
      contains=["measured since then: 0 runs, 0 tokens", "after 3 more: about 300,000 of 350,000"])
t.run("4 launches would go over", BUDGET, ["check", *P, "--launches", "4"], 1, contains=["room for 3 more"])
t.run("record 2 launches", BUDGET, ["check", *P, "--launches", "2", "--record"], 0, contains=["recorded 2 launches"])
t.check("recorded count saved", json.loads(budget_file.read_text())["recorded_launches"] == 2)
t.run("recorded runs not yet in transcripts still count", BUDGET, ["check", *P, "--launches", "2"], 1,
      contains=["recorded but not yet seen: 2 runs", "about 400,000 of 350,000"])
t.run("an over-budget check records nothing", BUDGET, ["check", *P, "--launches", "2", "--record"], 1)
t.check("recorded count unchanged after a refused launch", json.loads(budget_file.read_text())["recorded_launches"] == 2)

NEW = "2999-01-01T00:00:00Z"
t.jsonl(f"{sess}/agent-n1.jsonl", [turn("h", 120000, 0, 0, 5000, ts=NEW)])
t.jsonl(f"{sess}/agent-n2.jsonl", [turn("i", 20000, 0, 0, 0, ts=NEW)])
t.run("measured runs replace their reservation", BUDGET, ["check", *P, "--launches", "1"], 0,
      contains=["measured since then: 2 runs, 145,000 tokens", "recorded but not yet seen: 0 runs", "about 245,000 of 350,000"])
t.run("a real run bigger than planned shrinks the room", BUDGET, ["check", *P, "--launches", "3"], 1, contains=["room for 2 more"])
t.run("bad numbers are blocked", BUDGET, ["check", *P, "--launches", "-1"], 2, contains=["RESULT blocked"])
budget_file.write_text("{ broken")
t.run("a broken budget file is blocked", BUDGET, ["check", *P], 2, contains=["no usable budget file"])
sys.exit(t.done())

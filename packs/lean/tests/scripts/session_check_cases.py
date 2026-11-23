"""Script test for session-check: made-up transcripts with known usage numbers.

small.jsonl: 3 turns re-reading 1,000 / 2,000 / 3,000 tokens -> latest 3,000, below every line.
big.jsonl:   turn A is written over two lines with the same message id (output 10 then 40), so it counts once;
             re-read sizes 50,000 then 160,000 -> latest 160,000, over the default hand-off line of 150,000.

Usage: session_check_cases.py <folder>   (a new run folder is made inside it, for example .testrun/lean-session-check)
"""
import argparse
import os
import sys

import casekit

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("folder")
args = parser.parse_args()
t = casekit.Cases("session-check cases", args.folder)
SESSION = casekit.SKILLS / "session-check" / "scripts" / "session.py"
turn, user = casekit.turn, casekit.user

home = t.root / "home"
project = t.root / "work" / "shop"
project.mkdir(parents=True)
folder = f"home/.claude/projects/{casekit.slug(project)}"
old = t.jsonl(f"{folder}/old.jsonl", [user(), turn("o1", 5, 0, 0, 1)])
os.utime(old, (1_000_000_000, 1_000_000_000))
small = t.jsonl("small.jsonl", [user(), turn("s1", 1000, 0, 0, 50), user(), turn("s2", 100, 1900, 0, 60),
                                turn("s3", 100, 2600, 300, 70)])
big = t.jsonl("big.jsonl", [user(), turn("A", 50000, 0, 0, 10), turn("A", 50000, 0, 0, 40),
                            {"type": "system", "subtype": "compact_boundary"}, turn("B", 1000, 150000, 9000, 20)])

t.run("a small session passes", SESSION, [small, "--home", home], 0,
      contains=["assistant turns: 3", "re-read by each new message now: 3,000 tokens", "first turn 1,000", "output written so far: 180"])
out = t.run("a big session is a fail with the hand-off advice", SESSION, [big, "--home", home], 1,
            contains=["assistant turns: 2", "160,000 tokens", "compactions seen: 1", "output written so far: 60",
                      "the handoff skill is not installed"])
t.check("a reply split over two lines is counted once", "assistant turns: 2" in out.stdout)
t.run("the warning zone passes with a warning", SESSION, [big, "--home", home, "--warn-at", "100000", "--handoff-at", "200000"], 0,
      contains=["WARNING each new message re-reads 160,000", "hand off at the next natural break"])
t.run("--handoff-at moves the line", SESSION, [small, "--home", home, "--handoff-at", "2500", "--warn-at", "1000"], 1)

t.write("home/.claude/skills/handoff/SKILL.md", "---\nname: handoff\ndescription: test\n---\n")
t.run("an installed handoff skill is named in the advice", SESSION, [big, "--home", home], 1,
      contains=["run the handoff skill (found installed)"])

newest = t.jsonl(f"{folder}/newest.jsonl", [user(), turn("n1", 42000, 0, 0, 5)])
t.run("with no path the newest transcript for the folder is used", SESSION, ["--home", home, "--project", project], 0,
      contains=["session newest", "42,000 tokens"])
t.run("no transcript for the folder is blocked", SESSION, ["--home", home, "--project", t.root / "work"], 2,
      contains=["RESULT blocked: no session transcript found"])
t.run("a missing file is blocked", SESSION, [t.root / "nope.jsonl"], 2, contains=["RESULT blocked"])
nousage = t.jsonl("nousage.jsonl", [user(), {"type": "assistant", "message": {"id": "x", "content": []}}, "not json"])
t.run("no usage fields is not verified, with the file size", SESSION, [nousage, "--home", home], 2,
      contains=["1 lines not readable", "RESULT not verified: the transcript has no usage fields"])
t.check("the script printed no message text", "made-up" not in out.stdout)
sys.exit(t.done())

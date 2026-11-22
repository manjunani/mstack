"""Script test for eval-gate: build result files with known answers and check gate.py's verdict on each.

Usage: eval_gate_cases.py <folder>   (a new run folder is made inside it, for example .testrun/ai-eval-gate)
"""
import argparse
import sys

import casekit

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("folder")
args = parser.parse_args()
t = casekit.Cases("eval-gate cases", args.folder)
GATE = casekit.SKILLS / "eval-gate" / "scripts" / "gate.py"


def rows(spec, key="pass"):
    """spec: {case: [True, False, ...]} -> one row per trial."""
    return [{"case": c, "trial": i, key: v} for c, trials in spec.items() for i, v in enumerate(trials, 1)]


P, F = [True] * 3, [False] * 3
base = {f"c{i:02d}": P for i in range(1, 11)}
base.update({"c11": F, "c12": [True, True, False]})
t.jsonl("base.jsonl", rows(base))

t.jsonl("same.jsonl", rows(base))
t.run("identical runs pass", GATE, ["compare", "--baseline", "base.jsonl", "--candidate", "same.jsonl"], 0, contains=["difference +0.000"])

drop = dict(base, c01=F, c02=F, c03=F, c04=F, c05=F)
t.jsonl("drop.jsonl", rows(drop))
t.run("five cases lost fails", GATE, ["compare", "--baseline", "base.jsonl", "--candidate", "drop.jsonl"], 1,
      contains=["FLIP c01: pass to fail", "difference -0.417"])

better = dict(base, c11=P)
t.jsonl("better.jsonl", rows(better))
t.run("an improvement passes", GATE, ["compare", "--baseline", "base.jsonl", "--candidate", "better.jsonl"], 0,
      contains=["FLIP c11: fail to pass", "no shared case got worse"])

gone = {k: v for k, v in base.items() if k != "c11"}
t.jsonl("gone.jsonl", rows(gone))
t.run("a deleted failing case fails", GATE, ["compare", "--baseline", "base.jsonl", "--candidate", "gone.jsonl"], 1, contains=["MISSING c11"])
t.run("the same case retired by flag passes", GATE, ["compare", "--baseline", "base.jsonl", "--candidate", "gone.jsonl", "--retired", "c11"], 0)

two = {k: v[:2] for k, v in base.items()}
t.jsonl("two.jsonl", rows(two))
t.run("two trials per case is not verified", GATE, ["compare", "--baseline", "base.jsonl", "--candidate", "two.jsonl"], 2,
      contains=["not verified", "fewer than 3 trials"])

small = {k: base[k] for k in ("c01", "c02", "c03", "c04")}
t.jsonl("small-base.jsonl", rows(small))
t.jsonl("small-cand.jsonl", rows(dict(small, c01=F)))
t.run("four cases is not verified, even with a flip", GATE, ["compare", "--baseline", "small-base.jsonl", "--candidate", "small-cand.jsonl"], 2,
      contains=["only 4 cases"])

noisy = dict(base, c01=[True, True, False], c02=[True, False, False], c12=P)
t.jsonl("noisy.jsonl", rows(noisy))
t.run("a small mixed change is too small to tell", GATE, ["compare", "--baseline", "base.jsonl", "--candidate", "noisy.jsonl"], 2,
      contains=["too small to tell", "cases with this much spread"])

wobble = dict(base, c03=[True, True, False])
t.jsonl("wobble.jsonl", rows(wobble))
# One lost trial in 12 cases cannot be told from chance at the default allowed drop, so the honest answer is "not verified".
t.run("one lost trial is not verified at the default drop", GATE, ["compare", "--baseline", "base.jsonl", "--candidate", "wobble.jsonl"], 2,
      contains=["LESS STABLE c03", "too small to tell"])
t.run("the same lost trial passes when the user allows a 10 point drop", GATE,
      ["compare", "--baseline", "base.jsonl", "--candidate", "wobble.jsonl", "--max-drop", "0.1"], 0)
t.run("the same lost trial on a critical case fails", GATE, ["compare", "--baseline", "base.jsonl", "--candidate", "wobble.jsonl", "--critical", "c03"], 1,
      contains=["critical cases got worse: c03"])

scores = {f"s{i}": [0.9, 0.8, 0.7] for i in range(1, 4)}
scores["s4"] = [0.2, 0.6, 0.1]
t.jsonl("scores.jsonl", rows(scores, key="score"))
t.run("score rows are read with the pass score", GATE, ["summary", "scores.jsonl"], 0, contains=["passed every time: 3 of 4", "unstable: 1"])
t.run("a stricter pass score changes the count", GATE, ["summary", "scores.jsonl", "--pass-score", "0.75"], 0, contains=["passed every time: 0 of 4"])

t.write("bad.jsonl", '{"case": "a", "trial": 1, "pass": true}\n{"case": "a", "trial": 2}\nnot json\n')
t.run("rows without an outcome are blocked", GATE, ["compare", "--baseline", "base.jsonl", "--candidate", "bad.jsonl"], 2,
      contains=["RESULT blocked", "line 2", "line 3"])
t.jsonl("twice.jsonl", [{"case": "a", "trial": 1, "pass": True}, {"case": "a", "trial": 1, "pass": True}])
t.run("the same trial twice is blocked", GATE, ["summary", "twice.jsonl"], 2, contains=["appears twice"])
t.write("empty.jsonl", "")
t.run("an empty file is blocked", GATE, ["summary", "empty.jsonl"], 2, contains=["RESULT blocked"])

t.run("no saved baseline is blocked", GATE, ["compare", "--candidate", "same.jsonl"], 2, contains=["RESULT blocked: no baseline"])
t.run("saving a short file is refused", GATE, ["save", "two.jsonl"], 2, contains=["not saved"])
t.check("nothing was saved by the refused run", not (t.root / ".mstack" / "eval-gate" / "baseline.jsonl").exists())
t.run("save keeps the baseline", GATE, ["save", "base.jsonl", "--note", "prompt v1"], 0)
t.run("compare finds the saved baseline", GATE, ["compare", "--candidate", "drop.jsonl"], 1)
t.check("compare wrote its record", (t.root / ".mstack" / "eval-gate" / "last-compare.json").exists())
t.run("a second save without --replace is blocked", GATE, ["save", "better.jsonl"], 2, contains=["RESULT blocked"])
t.run("save --replace keeps the old one", GATE, ["save", "better.jsonl", "--replace"], 0, contains=["old baseline was kept"])
t.check("the input file was not changed", (t.root / "base.jsonl").read_text() == "".join(__import__("json").dumps(r) + "\n" for r in rows(base)))
sys.exit(t.done())

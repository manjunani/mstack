"""Script test for judge-check: label sets whose agreement and kappa were worked out by hand.

Usage: judge_check_cases.py <folder>   (a new run folder is made inside it, for example .testrun/ai-judge-check)
"""
import argparse
import sys

import casekit

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("folder")
args = parser.parse_args()
t = casekit.Cases("judge-check cases", args.folder)
AGREE = casekit.SKILLS / "judge-check" / "scripts" / "agree.py"


def build(cells, category=None):
    """cells: [(human, judge, count), ...] -> rows with running ids."""
    rows = []
    for human, judge, count in cells:
        for _ in range(count):
            row = {"id": f"ex-{len(rows) + 1:02d}", "human": human, "judge": judge}
            if category:
                row["category"] = category[len(rows) % len(category)]
            rows.append(row)
    return rows


# 40 examples, 35 agree. Chance agreement (20*21 + 20*19) / 1600 = 0.5, so kappa = (0.875 - 0.5) / 0.5 = 0.75.
t.jsonl("good.jsonl", build([("pass", "pass", 18), ("pass", "fail", 2), ("fail", "pass", 3), ("fail", "fail", 17)]))
t.run("a grader that agrees passes", AGREE, ["good.jsonl"], 0,
      contains=["agreement 0.875", "kappa 0.750", "grader passed 3 of 20 examples the human failed", "DISAGREE ex-19: human pass, grader fail"])
t.run("the same grader fails a stricter floor", AGREE, ["good.jsonl", "--min-kappa", "0.8"], 1, contains=["kappa 0.750 is below 0.8"])

# A grader that passes everything: 30 of 40 agree, chance agreement is also 0.75, kappa = 0.
t.jsonl("yes-man.jsonl", build([("pass", "pass", 30), ("fail", "pass", 10)]))
t.run("a grader that passes everything fails", AGREE, ["yes-man.jsonl"], 1, contains=["kappa 0.000", "agreement 0.750 is below 0.8"])

# High agreement, low kappa: 45 of 50 agree, chance (44*49 + 6*1) / 2500 = 0.8648, kappa = 0.0352 / 0.1352 = 0.260.
t.jsonl("skewed.jsonl", build([("pass", "pass", 44), ("fail", "pass", 5), ("fail", "fail", 1)]))
t.run("90% agreement with kappa 0.26 fails", AGREE, ["skewed.jsonl"], 1, contains=["agreement 0.900", "kappa 0.260"], absent=["agreement 0.900 is below"])

# Three labels: 24 of 30 agree, chance (10*9 + 10*12 + 10*9) / 900 = 1/3, kappa = 0.7.
three = [("good", "good", 8), ("good", "ok", 2), ("ok", "good", 1), ("ok", "ok", 8), ("ok", "bad", 1), ("bad", "ok", 2), ("bad", "bad", 8)]
t.jsonl("three.jsonl", build(three, category=["billing", "shipping"]))
t.run("three labels are handled", AGREE, ["three.jsonl"], 0, contains=["agreement 0.800", "kappa 0.700", "per category"])

t.jsonl("few.jsonl", build([("pass", "pass", 6), ("fail", "fail", 6)]))
t.run("twelve perfect examples are not verified", AGREE, ["few.jsonl"], 2, contains=["RESULT not verified: 12 examples are too few"])
t.jsonl("one-label.jsonl", build([("pass", "pass", 30)]))
t.run("only passing examples are not verified", AGREE, ["one-label.jsonl"], 2, contains=["every example has the human label 'pass'"])
t.jsonl("rare.jsonl", build([("pass", "pass", 28), ("fail", "fail", 2)]))
t.run("two failing examples are too few", AGREE, ["rare.jsonl"], 2, contains=["too few examples of fail (2)"])

silent = build([("pass", "pass", 17), ("fail", "fail", 16)]) + [{"id": f"s{i}", "human": "pass", "judge": None} for i in range(3)] + [{"id": "s9", "human": "fail"}]
t.jsonl("silent.jsonl", silent)
t.run("a missing verdict counts against the grader", AGREE, ["silent.jsonl"], 0, contains=["no verdict on 4 examples", "disagreements: 4"])

mixed = [{"id": i, "label": i % 2 == 0, "verdict": "PASS" if i % 2 == 0 else "Fail"} for i in range(40)]
t.jsonl("mixed-words.jsonl", mixed)
t.run("true/false and PASS/Fail are read as the same labels", AGREE, ["mixed-words.jsonl"], 0, contains=["agreement 1.000", "kappa 1.000"])

good = build([("pass", "pass", 18), ("pass", "fail", 2), ("fail", "pass", 3), ("fail", "fail", 17)])
t.jsonl("labels.jsonl", [{"id": r["id"], "human": r["human"]} for r in good])
t.jsonl("verdicts.jsonl", [{"id": r["id"], "judge": r["judge"]} for r in good] + [{"id": "stray", "judge": "pass"}])
t.run("two files joined on id give the same numbers", AGREE, ["--labels", "labels.jsonl", "--verdicts", "verdicts.jsonl"], 0,
      contains=["agreement 0.875", "kappa 0.750", "1 verdicts have no human label"])

t.jsonl("twice.jsonl", [{"id": "a", "human": "pass", "judge": "pass"}, {"id": "a", "human": "fail", "judge": "pass"}])
t.run("a repeated id is blocked", AGREE, ["twice.jsonl"], 2, contains=["RESULT blocked", "appears twice"])
t.jsonl("unlabelled.jsonl", [{"id": "a", "judge": "pass"}])
t.run("an example without a human label is blocked", AGREE, ["unlabelled.jsonl"], 2, contains=["has no human label"])
t.run("a missing file is blocked", AGREE, ["nope.jsonl"], 2, contains=["RESULT blocked: no examples file"])
t.run("one file plus --labels is blocked", AGREE, ["good.jsonl", "--labels", "labels.jsonl"], 2, contains=["RESULT blocked"])
sys.exit(t.done())

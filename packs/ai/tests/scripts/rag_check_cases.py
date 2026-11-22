"""Script test for rag-check: a 12-question gold set whose hit rates and MRR were worked out by hand.

Ranks of the answer passage in the first run: five at rank 1 (q01-q05), q06 and q07 at 2, q08 at 3, q09 at 5,
q10 at 8, q11 not retrieved, q12 at 1. So hit@1 = 6/12, hit@3 = 9/12, hit@5 = 10/12, hit@10 = 11/12 and
MRR = (6 + 2*0.5 + 1/3 + 1/5 + 1/8) / 12 = 0.638.

Usage: rag_check_cases.py <folder>   (a new run folder is made inside it, for example .testrun/ai-rag-check)
"""
import argparse
import sys

import casekit

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("folder")
args = parser.parse_args()
t = casekit.Cases("rag-check cases", args.folder)
SCORE = casekit.SKILLS / "rag-check" / "scripts" / "score.py"

QUESTIONS = [f"q{i:02d}" for i in range(1, 13)]
BASE_RANKS = {"q01": 1, "q02": 1, "q03": 1, "q04": 1, "q05": 1, "q06": 2, "q07": 2, "q08": 3, "q09": 5, "q10": 8, "q11": None, "q12": 1}


def gold(questions=QUESTIONS):
    return [{"id": q, "question": f"Question {q[1:]} about the handbook?", "answer_id": "p" + q[1:], "category": "billing" if int(q[1:]) % 2 else "shipping"}
            for q in questions]


def results(ranks, depth=10):
    """Put each question's answer passage at the given rank among filler ids; None leaves it out."""
    rows = []
    for q, rank in ranks.items():
        listed = [f"x{q[1:]}-{n}" for n in range(1, depth + 1)]
        if rank is not None:
            listed[rank - 1] = "p" + q[1:]
        rows.append({"id": q, "retrieved": listed})
    return rows


t.jsonl("gold.jsonl", gold())
t.jsonl("run1.jsonl", results(BASE_RANKS))
NUMBERS = "hit@1 0.500  hit@3 0.750  hit@5 0.833  hit@10 0.917   MRR 0.638"
t.run("measured, but nothing to judge against: not verified", SCORE, ["score", "--gold", "gold.jsonl", "--results", "run1.jsonl"], 2,
      contains=[NUMBERS, "MISS q10 (rank 8)", "MISS q11 (not retrieved)", "billing: 5 of 6", "no floor and no baseline"])
t.run("above a floor of 0.8 passes", SCORE, ["score", "--gold", "gold.jsonl", "--results", "run1.jsonl", "--floor", "0.8"], 0)
t.run("below a floor of 0.9 fails", SCORE, ["score", "--gold", "gold.jsonl", "--results", "run1.jsonl", "--floor", "0.9"], 1,
      contains=["hit@5 is 0.833, below the floor of 0.9"])
t.run("judged at k=10 the same run clears 0.9", SCORE, ["score", "--gold", "gold.jsonl", "--results", "run1.jsonl", "--floor", "0.9", "--at", "10"], 0)

t.run("save keeps the run as baseline", SCORE, ["save", "--gold", "gold.jsonl", "--results", "run1.jsonl", "--note", "index v1"], 0)
t.run("the same run against its own baseline passes", SCORE, ["score", "--gold", "gold.jsonl", "--results", "run1.jsonl"], 0, contains=["hit@5 0.833 -> 0.833 (+0.000)"])
t.run("a second save without --replace is blocked", SCORE, ["save", "--gold", "gold.jsonl", "--results", "run1.jsonl"], 2, contains=["RESULT blocked"])

t.jsonl("swap.jsonl", results(dict(BASE_RANKS, q06=None, q11=1)))
t.run("one lost, one found: passes and names both", SCORE, ["score", "--gold", "gold.jsonl", "--results", "swap.jsonl"], 0,
      contains=["NEWLY MISSED q06: rank 2 in the baseline, not retrieved now", "NEWLY FOUND q11: not retrieved in the baseline, rank 1 now"])
t.jsonl("worse.jsonl", results(dict(BASE_RANKS, q01=None, q02=None)))
t.run("two answers lost fails on the hit rate", SCORE, ["score", "--gold", "gold.jsonl", "--results", "worse.jsonl"], 1,
      contains=["hit@5 fell from 0.833 to 0.667", "NEWLY MISSED q01"])
t.jsonl("lower.jsonl", results(dict(BASE_RANKS, q01=4, q02=4, q03=4, q04=4, q05=4)))
t.run("answers pushed down the list fail on MRR alone", SCORE, ["score", "--gold", "gold.jsonl", "--results", "lower.jsonl"], 1,
      contains=["hit@5 0.833 -> 0.833", "MRR fell from 0.638 to 0.326"], absent=["hit@5 fell"])

t.jsonl("gold-cut.jsonl", gold([q for q in QUESTIONS if q != "q11"]))
t.jsonl("run-cut.jsonl", results({q: r for q, r in BASE_RANKS.items() if q != "q11"}))
t.run("a failing question removed from the gold file fails", SCORE, ["score", "--gold", "gold-cut.jsonl", "--results", "run-cut.jsonl"], 1,
      contains=["REMOVED q11", "1 baseline questions were removed"])
t.run("the same question retired by flag passes", SCORE, ["score", "--gold", "gold-cut.jsonl", "--results", "run-cut.jsonl", "--retired", "q11"], 0)

t.jsonl("partial.jsonl", results({q: r for q, r in BASE_RANKS.items() if q != "q12"}))
t.run("a question with no results row is not a miss and not a pass", SCORE, ["score", "--gold", "gold.jsonl", "--results", "partial.jsonl", "--floor", "0.5"], 2,
      contains=["NOT ANSWERED q12", "1 of 12 questions have no results row"], absent=["MISS q12"])
t.jsonl("gold-few.jsonl", gold(QUESTIONS[:6]))
t.jsonl("run-few.jsonl", results({q: BASE_RANKS[q] for q in QUESTIONS[:6]}))
t.run("six questions are too few for a verdict", SCORE, ["score", "--gold", "gold-few.jsonl", "--results", "run-few.jsonl", "--floor", "0.5", "--baseline", ".mstack/rag-check/baseline.json", "--retired", *QUESTIONS[6:]], 2,
      contains=["6 questions are too few"])
t.jsonl("shallow.jsonl", results({q: (r if r and r <= 3 else None) for q, r in BASE_RANKS.items()}, depth=3))
t.run("a named baseline that does not exist is blocked", SCORE, ["score", "--gold", "gold.jsonl", "--results", "shallow.jsonl", "--floor", "0.7", "--baseline", "none.json"], 2,
      contains=["RESULT blocked: no baseline at none.json"])
t.run("short lists: the note and the limited hit rate", SCORE, ["score", "--gold", "gold.jsonl", "--results", "shallow.jsonl", "--floor", "0.7", "--max-drop", "1"], 0,
      contains=["retrieved lists hold 3 to 3 ids", "12 lists are shorter than k=10", "hit@5 0.750"])

inline = [{"qid": f"n{i}", "question": "inline", "answer_ids": [f"a{i}", f"b{i}"], "retrieved": [{"chunk_id": f"z{i}"}, {"chunk_id": f"b{i}"}]} for i in range(1, 11)]
t.jsonl("inline.jsonl", inline)
t.run("a baseline from another question set is blocked", SCORE, ["score", "--gold", "inline.jsonl", "--floor", "0.9"], 2,
      contains=["RESULT blocked", "shares no question with this gold file"])
t.run("ranked ids inside the gold rows, objects as items, two answer passages", SCORE, ["score", "--gold", "inline.jsonl", "--floor", "0.9", "--no-baseline"], 0,
      contains=["hit@1 0.000", "hit@3 1.000", "MRR 0.500"])

t.jsonl("dup.jsonl", gold() + gold(["q01"]))
t.run("a question listed twice is blocked", SCORE, ["score", "--gold", "dup.jsonl", "--results", "run1.jsonl"], 2, contains=["q01 appears twice"])
t.jsonl("no-answer.jsonl", [{"id": "q1", "question": "?"}])
t.run("a gold row without an answer passage is blocked", SCORE, ["score", "--gold", "no-answer.jsonl", "--results", "run1.jsonl"], 2, contains=["has no answer passage id"])
t.run("no retrieved ids anywhere is blocked", SCORE, ["score", "--gold", "gold.jsonl"], 2, contains=["RESULT blocked: no question has a list of retrieved ids"])
t.run("a missing gold file is blocked", SCORE, ["score", "--gold", "nope.jsonl"], 2, contains=["RESULT blocked: no gold file"])
t.run("save refuses a run with unanswered questions", SCORE, ["save", "--gold", "gold.jsonl", "--results", "partial.jsonl", "--replace"], 2, contains=["not saved"])
t.check("the refused save left the baseline as it was", '"note": "index v1"' in (t.root / ".mstack" / "rag-check" / "baseline.json").read_text())
sys.exit(t.done())

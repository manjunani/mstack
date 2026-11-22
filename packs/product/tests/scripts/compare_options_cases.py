"""Run compare-options' compare.py on comparisons whose flip points were worked out by hand.

The worked example (scale 1 to 5, weights cost 3, ops 2, speed 1, veto on ops below 2):
  Postgres  cost 4, ops 3, speed 2  -> (12 + 6 + 2) / 6 = 3.33
  Redis     cost 2, ops 5, speed 3  -> ( 6 + 10 + 3) / 6 = 3.17
  Kafka     cost 5, ops 1, speed 5  -> vetoed (ops 1 is below 2); it would total 3.67
  Margin 0.17. Postgres leads Redis by 1 weighted point (20 - 19).
  Weight flips: cost 3 -> 2.5 (lead 1 / score gap 2), ops 2 -> 2.5, speed 1 -> 2.
  Score flips:  Postgres cost 4 -> 3.67 (lead 1 / weight 3), Redis cost 2 -> 2.33, Postgres ops 3 -> 2.5,
                Kafka ops 1 -> 2 (the veto lifts and its total becomes 4).
Usage: compare_options_cases.py <path to compare.py> <new folder>
"""
import argparse
import copy
import json

import casekit

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("script")
parser.add_argument("folder")
args = parser.parse_args()
c = casekit.Cases(args.script, args.folder, "compare-options")


def option(name, cost, ops, speed, source="price list and docs read on 2026-11-20"):
    return {"name": name, "scores": {"cost": {"score": cost, "source": source}, "ops": {"score": ops, "source": source},
                                     "speed": {"score": speed, "source": source}}}


base = {
    "decision": "Which queue runs the background jobs?",
    "scale": {"min": 1, "max": 5},
    "criteria": [{"name": "cost", "weight": 3}, {"name": "ops", "weight": 2, "veto_below": 2}, {"name": "speed", "weight": 1}],
    "options": [option("Postgres", 4, 3, 2), option("Redis", 2, 5, 3), option("Kafka", 5, 1, 5)],
}


def variant(name, change):
    data = copy.deepcopy(base)
    change(data)
    return c.write(f"{name}.json", data).name


c.run("no file is blocked", 2, "rank", "missing.json", expect="does not exist")
c.run("template writes a skeleton", 0, "template", "skeleton.json", "--decision", "Which queue?")
c.run("template refuses to overwrite", 2, "template", "skeleton.json", "--decision", "Which queue?")
c.run("the untouched skeleton is refused", 2, "rank", "skeleton.json", expect="REFUSED")

c.write("queue.json", base)
before = (c.folder / "queue.json").read_text(encoding="utf-8")
out = c.run("the worked example ranks Postgres first", 0, "rank", "queue.json", expect="First: Postgres, ahead of Redis by 0.17 points")
c.check("totals match the hand calculation", "Postgres                     3.33" in out and "Redis                        3.17" in out)
c.check("Kafka is removed by the veto although its total would be highest", "out  Kafka" in out and "'ops' is 1, below 2" in out)
c.check("weight flip: cost 3 -> 2.5 ties with Redis", "weight of 'cost' from 3 to 2.5 (-0.50): ties with Redis" in out)
c.check("weight flip: ops 2 -> 2.5 ties with Redis", "weight of 'ops' from 2 to 2.5 (+0.50): ties with Redis" in out)
c.check("score flip: Postgres cost 4 -> 3.67", "Postgres / 'cost' from 4 to 3.67 (-0.33): ties with Redis" in out)
c.check("score flip: Redis cost 2 -> 2.33", "Redis / 'cost' from 2 to 2.33 (+0.33): ties with Postgres" in out)
c.check("a winner that one point can unseat is called fragile", "the result is fragile" in out)
result = json.loads((c.folder / "queue.result.json").read_text(encoding="utf-8"))
c.check("the result file names the winner and the margin", result["winner"] == "Postgres" and abs(result["margin"] - 0.1667) < 0.001)
flips = {(f["option"], f["criterion"]): f for f in result["score_flips"]}
c.check("lifting Kafka's veto (ops 1 -> 2) is found as a flip", ("Kafka", "ops") in flips and abs(flips[("Kafka", "ops")]["to"] - 2) < 1e-9)
c.check("the input file was not changed", (c.folder / "queue.json").read_text(encoding="utf-8") == before)

# Apply the reported flips and confirm that first place really changes.
c.run("at cost weight 2.4 (past the flip at 2.5) Redis is first", 0, "rank",
      variant("pastweight", lambda d: d["criteria"][0].update(weight=2.4)), expect="First: Redis")
c.run("at cost weight 2.6 (short of the flip) Postgres is still first", 0, "rank",
      variant("shortweight", lambda d: d["criteria"][0].update(weight=2.6)), expect="First: Postgres")
c.run("at the flip weight itself first place is tied, which is a fail", 1, "rank",
      variant("tieweight", lambda d: d["criteria"][0].update(weight=2.5)), expect="tied between Postgres and Redis")
c.run("with Postgres cost at 3.6 (past 3.67) Redis is first", 0, "rank",
      variant("pastscore", lambda d: d["options"][0]["scores"]["cost"].update(score=3.6)), expect="First: Redis")
c.run("with Kafka ops at 2 the veto lifts and Kafka is first", 0, "rank",
      variant("unveto", lambda d: d["options"][2]["scores"]["ops"].update(score=2)), expect="First: Kafka")
c.run("a veto on the winner hands first place to the next option", 0, "rank",
      variant("vetowinner", lambda d: d["criteria"][2].update(veto_below=3)), expect="First: Redis")

out = c.run("a dominant option has no weight flip; only falling under the veto limit unseats it", 0, "rank",
            variant("dominant", lambda d: d.update(options=[option("Strong", 5, 5, 5), option("Weak", 1, 2, 1)])),
            expect="none: no single weight")
c.check("the veto flip is reported as such, and the result is not called fragile",
        "Strong / 'ops' from 5 to 2 (-3.00): below 2 is a veto, so Weak leads" in out and "fragile" not in out)
c.run("the same pair with no veto has no score flip at all", 0, "rank",
      variant("dominant2", lambda d: (d.update(options=[option("Strong", 5, 5, 5), option("Weak", 1, 2, 1)]), d["criteria"][1].pop("veto_below"))),
      expect="none: no single score")
out = c.run("a score from an estimate is reported as soft", 0, "rank",
            variant("soft", lambda d: d["options"][0]["scores"]["cost"].update(source="my rough estimate, no quote yet")),
            expect="1 score(s) rest on an estimate: Postgres / cost")
c.check("and the flip that sits on it is marked", "[soft score]" in out)

c.run("every option vetoed is a fail", 1, "rank",
      variant("allout", lambda d: d["criteria"][0].update(veto_below=5) or d["options"][2]["scores"]["cost"].update(score=4)),
      expect="every option is vetoed")
c.run("a missing weight is refused", 2, "rank", variant("noweight", lambda d: d["criteria"][1].pop("weight")),
      expect="criterion 'ops': the weight is missing")
c.run("a weight of zero is refused", 2, "rank", variant("zeroweight", lambda d: d["criteria"][1].update(weight=0)), expect="not a positive number")
c.run("a weight written as a word is refused", 2, "rank", variant("wordweight", lambda d: d["criteria"][1].update(weight="high")),
      expect="the weight is missing")
c.run("a score with no source is refused", 2, "rank",
      variant("nosource", lambda d: d["options"][1]["scores"]["speed"].pop("source")), expect="'Redis' / 'speed': score 3 has no stated source")
c.run("a placeholder source is refused", 2, "rank",
      variant("tbdsource", lambda d: d["options"][1]["scores"]["speed"].update(source="TBD")), expect="has no stated source")
c.run("a missing score is refused", 2, "rank",
      variant("noscore", lambda d: d["options"][1]["scores"].pop("ops")), expect="'Redis' has no score for 'ops'")
c.run("a score off the scale is refused", 2, "rank",
      variant("offscale", lambda d: d["options"][1]["scores"]["ops"].update(score=9)), expect="off the scale 1 to 5")
c.run("a score for an unlisted criterion is refused", 2, "rank",
      variant("extra", lambda d: d["options"][1]["scores"].update(looks={"score": 5, "source": "the landing page"})), expect="not a listed criterion")
c.run("one option is not a comparison", 2, "rank", variant("single", lambda d: d.update(options=d["options"][:1])), expect="at least two")
c.run("a name used twice is refused", 2, "rank", variant("twice", lambda d: d["options"][1].update(name="Postgres")), expect="listed twice")
c.run("a veto limit off the scale is refused", 2, "rank", variant("badveto", lambda d: d["criteria"][1].update(veto_below=7)), expect="veto_below must be on the scale")
c.run("all refusals are listed together, and nothing is ranked", 2, "rank",
      variant("several", lambda d: (d["criteria"][1].pop("weight"), d["options"][1]["scores"]["speed"].pop("source"))), expect="2 gap(s)")
c.write("broken.json", "{ not json")
c.run("a file that is not JSON is refused", 2, "rank", "broken.json", expect="not valid JSON")
c.done()

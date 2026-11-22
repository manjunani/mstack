"""Run premortem's assumptions.py on a table whose ranking was worked out by hand.

The worked table (risk = impact x (6 - counted confidence)):
  A-01  impact 5, confidence 2                         -> 5 x 4 = 20
  A-02  impact 4, confidence 3                         -> 4 x 3 = 12
  A-03  impact 3, confidence 5 with evidence           -> 3 x 1 = 3
  A-04  impact 4, confidence 5 with NO evidence -> 2   -> 4 x 4 = 16
  A-05  impact 3, confidence 4, rests on A-04 -> 2     -> 3 x 4 = 12
  A-06  impact 2, confidence 2                         -> 2 x 4 = 8
  Order: A-01, A-04, A-02 (impact 4 beats A-05's 3 at equal risk), A-05, A-06, A-03. Top three: A-01, A-04, A-02.
Usage: premortem_cases.py <path to assumptions.py> <new folder>
"""
import argparse
import copy

import casekit

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("script")
parser.add_argument("folder")
args = parser.parse_args()
c = casekit.Cases(args.script, args.folder, "premortem")

c.write("docs/specs/export.md", "# Spec: CSV export\n\n## Done when\n\n- R-001: A file is downloaded. Check: demo: click the button\n")


def test(what, cost, passes, fails):
    return {"what": what, "cost": cost, "pass": passes, "fail": fails}


base = {
    "plan": "docs/specs/export.md",
    "failure": "Three months on, both accountants still copy rows by hand; the export button is used twice a month, by the developer.",
    "assumptions": [
        {"id": "A-01", "statement": "The accountants will work from a file instead of the screen.", "impact": 5, "confidence": 2,
         "test": test("Hand both accountants a CSV made by hand from last month's report and watch the check.", "2 hours",
                      "Both finish the month-end check from the file with 0 rows copied by hand.", "Either one goes back to the screen for more than 5 rows.")},
        {"id": "A-02", "statement": "The browser can build a 10,000-row file without freezing the page.", "impact": 4, "confidence": 3,
         "test": test("Build the file from 10,000 generated rows in a scratch page.", "1 day",
                      "The file is ready in under 2 seconds.", "It takes 2 seconds or more, or the tab stops responding.")},
        {"id": "A-03", "statement": "The rows on screen are the rows held in memory.", "impact": 3, "confidence": 5,
         "evidence": "Read src/reports.py: one function builds the list the page renders."},
        {"id": "A-04", "statement": "The month-end totals are checked from this page only.", "impact": 4, "confidence": 5,
         "test": test("Ask both accountants which screens they open during the check.", "30 min",
                      "Both name this page and 0 others.", "Either names 1 or more other screens.")},
        {"id": "A-05", "statement": "The file opens with the right columns in their spreadsheet.", "impact": 3, "confidence": 4,
         "evidence": "Opened a sample file in the same spreadsheet version.", "depends_on": ["A-04"]},
        {"id": "A-06", "statement": "Nobody needs the Excel format.", "impact": 2, "confidence": 2},
    ],
}


def variant(name, change):
    data = copy.deepcopy(base)
    change(data)
    return c.write(f"{name}.json", data).name


c.run("no file is blocked", 2, "rank", "missing.json", expect="does not exist")
c.run("template writes a skeleton", 0, "template", "skeleton.json", "--plan", "docs/specs/export.md")
c.run("template refuses to overwrite", 2, "template", "skeleton.json", "--plan", "docs/specs/export.md")
c.run("the untouched skeleton is refused", 2, "rank", "skeleton.json", expect="at least three")

c.write("table.json", base)
before = (c.folder / "table.json").read_text(encoding="utf-8")
out = c.run("the worked table passes: its three top risks have tests", 0, "rank", "table.json", expect="top-ranked: A-01, A-04, A-02")
rows = [line.split("|")[2].strip() for line in out.splitlines() if line.startswith("| ") and "A-" in line]
c.check("the full order matches the hand calculation", rows == ["A-01", "A-04", "A-02", "A-05", "A-06", "A-03"])
c.check("the risk numbers match", "| A-01 | 20 |" in out and "| A-04 | 16 |" in out and "| A-02 | 12 |" in out and "| A-03 | 3 |" in out)
c.check("confidence with no evidence is counted as 2", "A-04: confidence 5 with no evidence, counted as 2" in out)
c.check("an assumption is no surer than the one it rests on", "A-05: rests on A-04 (confidence 2), counted as 2" in out)
c.check("the weakest link is named", "Weakest link: A-01" in out)
c.check("the cheapest test among the top risks is the 30-minute one", "Cheapest test among the top risks: A-04, 30 min" in out)
c.check("the ranked table was written beside the input", (c.folder / "table.ranked.md").is_file())
c.check("the input file was not changed", (c.folder / "table.json").read_text(encoding="utf-8") == before)

c.run("a top-ranked risk with no test fails", 1, "rank", variant("notest", lambda d: d["assumptions"][3].pop("test")),
      expect="A-04 (risk 16) has no test")
c.run("with evidence, A-04 drops out of the top and needs no test; A-05 takes its place and has none", 1, "rank",
      variant("evidence", lambda d: (d["assumptions"][3].pop("test"), d["assumptions"][3].update(evidence="Both accountants were watched doing the March check."))),
      expect="A-06 (risk 8) has no test")
c.run("with evidence for A-04 and tests on the new top three, it passes", 0, "rank",
      variant("evidence2", lambda d: (d["assumptions"][3].update(evidence="Both accountants were watched doing the March check."),
                                      d["assumptions"][5].update(test=test("Ask both accountants which file type they open.", "15 min",
                                                                           "0 of 2 ask for Excel.", "1 or more ask for Excel.")))),
      expect="top-ranked: A-01, A-02, A-06")
c.run("a test with no fail line fails", 1, "rank", variant("nofail", lambda d: d["assumptions"][0]["test"].pop("fail")),
      expect="A-01: its test has no fail line")
c.run("a test with no pass line fails", 1, "rank", variant("nopass", lambda d: d["assumptions"][0]["test"].update({"pass": "TBD"})),
      expect="A-01: its test has no pass line")
c.run("identical pass and fail lines fail", 1, "rank",
      variant("same", lambda d: d["assumptions"][0]["test"].update(fail=d["assumptions"][0]["test"]["pass"])), expect="are the same")
c.run("a cost that is not an amount of time fails", 1, "rank",
      variant("cost", lambda d: d["assumptions"][0]["test"].update(cost="cheap")), expect="must be an amount of time")
c.run("lines with no number warn and still pass", 0, "rank",
      variant("nonumber", lambda d: d["assumptions"][0]["test"].update({"pass": "Both finish from the file alone.", "fail": "Either goes back to the screen."})),
      expect="neither line has a number")
c.run("a low-confidence, high-impact bet outside --top still needs its test", 1, "rank", "--top", "1",
      variant("bet", lambda d: d["assumptions"][3].pop("test")), expect="A-04 (risk 16) has no test")
c.run("--top 5 pulls in rows that have no test", 1, "rank", "--top", "5", "table.json", expect="A-05 (risk 12) has no test")
c.run("a top risk marked not reversible is pointed out", 0, "rank",
      variant("oneway", lambda d: d["assumptions"][0].update(reversible=False)), expect="A-01: marked as not reversible")

c.run("no written plan is blocked", 2, "rank", variant("noplan", lambda d: d.update(plan="docs/specs/nothing.md")), expect="is not a file under")
c.run("no failure story is blocked", 2, "rank", variant("nostory", lambda d: d.update(failure="It failed.")), expect="failure is empty or too short")
c.run("fewer than three assumptions is blocked", 2, "rank", variant("two", lambda d: d.update(assumptions=d["assumptions"][:2])), expect="at least three")
c.run("an impact off the 1 to 5 scale is blocked", 2, "rank", variant("impact", lambda d: d["assumptions"][0].update(impact=7)), expect="impact must be a whole number from 1 to 5")
c.run("a confidence given as a word is blocked", 2, "rank", variant("word", lambda d: d["assumptions"][0].update(confidence="high")), expect="confidence must be")
c.run("a dependency on an unknown id is blocked", 2, "rank", variant("unknown", lambda d: d["assumptions"][4].update(depends_on=["A-99"])), expect="depends on 'A-99'")
c.run("a circle of dependencies is blocked", 2, "rank",
      variant("circle", lambda d: (d["assumptions"][3].update(depends_on=["A-05"]))), expect="in a circle")
c.run("a repeated id is blocked", 2, "rank", variant("dupe", lambda d: d["assumptions"][5].update(id="A-01")), expect="used twice")
c.write("broken.json", "{ not json")
c.run("a file that is not JSON is blocked", 2, "rank", "broken.json", expect="not valid JSON")
c.done()

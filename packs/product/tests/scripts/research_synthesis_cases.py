"""Run research-synthesis' evidence.py on three short invented interview notes and findings built from them.

Usage: research_synthesis_cases.py <path to evidence.py> <new folder>
"""
import argparse
import copy

import casekit

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("script")
parser.add_argument("folder")
args = parser.parse_args()
c = casekit.Cases(args.script, args.folder, "research-synthesis")

c.write("notes/p1.md", "Interview 1\n\nQ: How do you do month end?\nA: I copy every row by hand into a sheet.\nIt takes me most of a Friday.\n\n"
        + "".join(f"Small talk line {n}.\n" for n in range(1, 11)) + "A: I “don't trust” the totals on screen.\n")
c.write("notes/p2.md", "Interview 2\n\nA: Copying rows by hand is the worst part of the month.\nA: I would pay for an export.\n")
c.write("notes/p3.md", "Interview 3\n\nA: Honestly I copy rows by hand too,\nmaybe two hundred of them.\n")

base = {
    "threshold": 3,
    "sources": [{"file": "notes/p1.md", "participant": "P1"}, {"file": "notes/p2.md", "participant": "P2"},
                {"file": "notes/p3.md", "participant": "P3"}],
    "themes": [
        {"id": "T-01", "title": "Rows are copied by hand", "claim": "All three copy report rows by hand at month end.", "label": "theme",
         "evidence": [{"source": "notes/p1.md", "line": 4, "quote": "I copy every row by hand into a sheet."},
                      {"source": "notes/p2.md", "line": 3, "quote": "Copying rows by hand is the worst part"},
                      {"source": "notes/p3.md", "line": "3-4", "quote": "I copy rows by hand too, maybe two hundred"}]},
        {"id": "T-02", "title": "Distrust of on-screen totals", "claim": "One accountant does not trust the totals shown.", "label": "anecdote",
         "evidence": [{"source": "notes/p1.md", "line": 17, "quote": "I \"don't trust\" the totals"}]},
    ],
}


def variant(name, change):
    data = copy.deepcopy(base)
    change(data)
    return c.write(f"{name}.json", data).name


c.run("number prints sources with line numbers", 0, "number", "notes/p2.md", expect="    3  A: Copying rows")
c.run("number of a missing file is blocked", 2, "number", "notes/none.md")
c.run("no findings file is blocked", 2, "check", "missing.json", expect="does not exist")
c.run("template writes a skeleton", 0, "template", "skeleton.json")
c.run("template refuses to overwrite", 2, "template", "skeleton.json")
c.run("the untouched skeleton is blocked", 2, "check", "skeleton.json", expect="BLOCKED")

out = c.run("verbatim quotes, a three-person theme and a labelled anecdote pass", 0, "check", variant("good", lambda d: None), expect="RESULT pass")
c.check("the theme counts three distinct participants", "T-01  theme    3 participant(s) (P1, P2, P3)" in out)
c.check("a quote over a line break is verified with a line range", "3 quote(s) verified" in out)
c.check("curly quotes in the source match straight quotes in the finding", "T-02  anecdote 1 participant(s) (P1), 1 quote(s) verified" in out)
c.check("the uncited stretch in p1 (line 5, a blank, then small talk to 16) is listed", "uncited: lines 5-16" in out)
c.check("coverage is reported per source over non-blank lines", "notes/p2.md (P2): 33% of 3 lines cited" in out)

c.run("a reworded quote fails", 1, "check",
      variant("reworded", lambda d: d["themes"][0]["evidence"][0].update(quote="I copy all rows by hand into a sheet.")), expect="not found word for word")
c.run("a quote on the wrong line fails and says where it is", 1, "check",
      variant("wrongline", lambda d: d["themes"][0]["evidence"][1].update(line=4)), expect="it is at line 3")
c.run("a line past the end of the source fails", 1, "check",
      variant("pastend", lambda d: d["themes"][0]["evidence"][1].update(line=40)), expect="is not a line of notes/p2.md")
c.run("a two-person 'theme' fails: it is an anecdote", 1, "check",
      variant("two", lambda d: d["themes"][0]["evidence"].pop(2)), expect="under 3 it is an anecdote")
c.run("two quotes from the same person count once", 1, "check",
      variant("sameperson", lambda d: d["themes"][0]["evidence"].__setitem__(2, {"source": "notes/p2.md", "line": 4, "quote": "I would pay for an export."})),
      expect="2 distinct participant(s)")
c.run("an unverified quote does not count toward the threshold", 1, "check",
      variant("badcount", lambda d: d["themes"][0]["evidence"][2].update(quote="I hate month end")), expect="labelled a theme with 2")
c.run("a lower threshold makes the two-person finding a theme", 0, "check",
      variant("lower", lambda d: (d.update(threshold=2), d["themes"][0]["evidence"].pop(2))))
c.run("an anecdote that reached the threshold is noted, not failed", 0, "check",
      variant("bigger", lambda d: d["themes"][0].update(label="anecdote")), expect="it may be a theme")
c.run("a source that is not listed fails", 1, "check",
      variant("unlisted", lambda d: d["themes"][1]["evidence"][0].update(source="notes/p9.md")), expect="not one of the listed sources")
c.run("a listed source file that does not exist is blocked", 2, "check",
      variant("nofile", lambda d: d["sources"].append({"file": "notes/p4.md", "participant": "P4"})), expect="is not a file under")
c.run("a source with no participant is blocked", 2, "check",
      variant("nowho", lambda d: d["sources"][2].update(participant="")), expect="no participant")
c.run("a finding with no evidence is blocked", 2, "check",
      variant("noevidence", lambda d: d["themes"][1].update(evidence=[])), expect="a finding with no evidence")
c.run("a threshold of 1 is blocked", 2, "check", variant("one", lambda d: d.update(threshold=1)), expect="at least 2")
c.write("broken.json", "{ nope")
c.run("a file that is not JSON is blocked", 2, "check", "broken.json", expect="not valid JSON")
c.done()

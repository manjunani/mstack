"""Run clarify's intent.py on good and bad intent files in a new folder and compare exit codes.

Usage: clarify_cases.py <path to intent.py> <new folder>
"""
import argparse
import copy
import json

import casekit

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("script")
parser.add_argument("folder")
args = parser.parse_args()
c = casekit.Cases(args.script, args.folder, "clarify")

c.write("src/reports.py", "def rows():\n    return []\n")
good = {
    "title": "CSV export for the reports page",
    "restatement": {
        "outcome": "A person on the reports page can download the rows they see as a CSV file.",
        "user": "The two accountants who check totals by hand every month.",
        "why_now": "Month end is on the 30th and they copy rows by hand today.",
        "success": "Both accountants do the month-end check from the file without copying rows.",
        "constraint": "No new server dependency.",
        "out_of_scope": "Excel files, scheduled exports, archived rows.",
    },
    "entries": [
        {"id": "I-01", "statement": "The export holds the rows as filtered on screen, not all rows.", "status": "settled",
         "changes_build": True, "source": "user chose", "rejected": "export every row", "reason": "they check one client at a time"},
        {"id": "I-02", "statement": "Reports are built as a list of rows in one function.", "status": "settled",
         "changes_build": True, "source": "found in repo", "where": "src/reports.py:1"},
        {"id": "I-03", "statement": "The accountants open the file in a spreadsheet.", "status": "settled",
         "changes_build": True, "source": "user said"},
        {"id": "I-04", "statement": "The file name carries today's date.", "status": "settled",
         "changes_build": False, "source": "assumed"},
    ],
}


def variant(name, change):
    data = copy.deepcopy(good)
    change(data)
    return c.write(f"{name}.json", data).name


c.run("no file is blocked", 2, "check", "missing.json", expect="does not exist")
c.run("template writes a skeleton", 0, "template", "skeleton.json", "--title", "Export")
c.run("template refuses to overwrite", 2, "template", "skeleton.json", "--title", "Export", expect="not overwritten")
c.run("the untouched skeleton fails", 1, "check", "skeleton.json", expect="'outcome' is empty")

c.write("good.json", good)
c.run("complete but unconfirmed is blocked, not a pass", 2, "check", "good.json", expect="has not confirmed")
c.run("confirm records the user's words", 0, "confirm", "good.json", "--words", "yes, that is it")
c.run("complete and confirmed passes", 0, "check", "good.json", expect="RESULT pass")
c.run("show prints the rejected alternative", 0, "show", "good.json", expect="instead of: export every row")

changed = json.loads((c.folder / "good.json").read_text(encoding="utf-8"))
changed["restatement"]["out_of_scope"] = "Excel files only."
c.write("edited.json", changed)
c.run("an edit after the yes voids the confirmation", 2, "check", "edited.json", expect="changed after the user confirmed")

c.run("an entry with no provenance label fails", 1, "check",
      variant("nolabel", lambda d: d["entries"][2].pop("source")), expect="no provenance label")
c.run("an invented label fails", 1, "check",
      variant("badlabel", lambda d: d["entries"][2].update(source="common sense")), expect="no provenance label")
c.run("a user decision with no rejected alternative fails", 1, "check",
      variant("norejected", lambda d: d["entries"][0].pop("rejected")), expect="rejected alternative")
c.run("a user decision with no reason fails", 1, "check",
      variant("noreason", lambda d: d["entries"][0].update(reason="TBD")), expect="must give the reason")
c.run("an assumption that changes the build fails", 1, "check",
      variant("assumed", lambda d: d["entries"][3].update(changes_build=True)), expect="assumed, and it changes the build")
c.run("an open item that changes the build fails", 1, "check",
      variant("open", lambda d: d["entries"].append({"id": "I-05", "statement": "Which separator, comma or semicolon?", "status": "open", "changes_build": True})),
      expect="open and it changes the build")
c.run("an open item that does not change the build is only a note", 2, "check",
      variant("opensmall", lambda d: d["entries"].append({"id": "I-05", "statement": "Colour of the button?", "status": "open", "changes_build": False})),
      expect="note  I-05")
c.run("'found in repo' pointing at a missing file fails", 1, "check",
      variant("nowhere", lambda d: d["entries"][1].update(where="src/gone.py:3")), expect="was not found")
c.run("'found in repo' pointing outside the project fails", 1, "check",
      variant("outside", lambda d: d["entries"][1].update(where="../../casekit.py")), expect="was not found")
c.run("a comparison written with angle signs is not taken for a placeholder", 2, "check",
      variant("angles", lambda d: d["restatement"].update(success="Export takes < 2 s and holds > 100 rows.")), absent="placeholder")
c.run("a placeholder in the restatement fails", 1, "check",
      variant("placeholder", lambda d: d["restatement"].update(success="TBD")), expect="'success' is empty or a placeholder")
c.run("a repeated id fails", 1, "check",
      variant("dupe", lambda d: d["entries"][3].update(id="I-01")), expect="used twice")
c.run("confirm refuses a file that still has problems", 1, "confirm",
      variant("confirmbad", lambda d: d["entries"][3].update(changes_build=True)), "--words", "yes", expect="not confirmed")
c.write("broken.json", "{ not json")
c.run("a file that is not JSON is blocked", 2, "check", "broken.json", expect="not valid JSON")
c.done()

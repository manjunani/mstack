"""Run ideate's options.py through list, freeze, judge and check in a new folder and compare exit codes.

Usage: ideate_cases.py <path to options.py> <new folder>
"""
import argparse
import copy
import json

import casekit

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("script")
parser.add_argument("folder")
args = parser.parse_args()
c = casekit.Cases(args.script, args.folder, "ideate")

c.write("src/reports.py", "def rows():\n    return []\n")
TITLES = [
    "Download button that writes a CSV in the browser",
    "Server route that streams the CSV",
    "Nightly email with the report attached",
    "Copy the table to the clipboard as tab-separated text",
    "Shared read-only link to the filtered view",
    "Print stylesheet so the page prints as a table",
    "Spreadsheet add-on that pulls rows through the API",
    "Saved filter plus a totals row so no export is needed",
    "Webhook that posts the rows to the accounting tool",
]
listed = {
    "question": "How could the accountants get report rows out for the month-end check?",
    "target": 8,
    "grounding": [
        {"where": "src/reports.py:1", "note": "Rows are built by one function as a list."},
        {"source": "user said", "note": "They check one client at a time and copy rows by hand today."},
    ],
    "options": [{"id": f"O-{n:02d}", "title": t, "how": "one line", "status": "candidate"} for n, t in enumerate(TITLES, 1)],
}


def save(name, data):
    return c.write(f"{name}.json", data).name


def variant(base, name, change):
    data = copy.deepcopy(base)
    change(data)
    return save(name, data)


def judge(data, survivors=("O-01", "O-04"), reason="Needs the mail service, which the project does not have yet."):
    for option in data["options"]:
        if option["id"] in survivors:
            option.update(status="survivor", basis="Rows are already one list in memory, so this needs no new service.", where="src/reports.py")
        else:
            option.update(status="rejected", reason=f"{reason} ({option['id']})")


c.run("no file is blocked", 2, "check", "missing.json", expect="does not exist")
c.run("template writes a skeleton", 0, "template", "skeleton.json", "--question", "How could rows be exported?", "--target", "10")
c.run("template refuses to overwrite", 2, "template", "skeleton.json", "--question", "How could rows be exported?")
c.run("the skeleton cannot be frozen", 1, "freeze", "skeleton.json", expect="grounding is empty")
c.run("check before any freeze is not verified", 2, "check", save("unfrozen", listed), expect="never frozen")

c.run("too few options cannot be frozen", 1, "freeze",
      variant(listed, "few", lambda d: d.update(options=d["options"][:5])), expect="5 distinct options; the target is 8")
c.run("a target below the minimum is refused", 1, "freeze", variant(listed, "lowtarget", lambda d: d.update(target=3)), expect="at least 8")
c.run("reworded duplicates count once", 1, "freeze",
      variant(listed, "twins", lambda d: d.update(options=d["options"][:7] + [
          {"id": "O-08", "title": "A download button that writes the CSV in a browser", "status": "candidate"},
          {"id": "O-09", "title": "Button: download, writes CSV in the browser", "status": "candidate"}])),
      expect="7 distinct options")
c.run("a list that is already partly judged cannot be frozen", 1, "freeze",
      variant(listed, "early", lambda d: d["options"][2].update(status="rejected", reason="Too much work for now, honestly.")), expect="already judged: O-03")
c.run("grounding that points at a missing file fails", 1, "freeze",
      variant(listed, "nogrounding", lambda d: d["grounding"][0].update(where="src/gone.py")), expect="was not found")
c.run("an axis with no option fails", 1, "freeze",
      variant(listed, "axes", lambda d: (d.update(axes=["in the page", "outside the page"]), [o.update(axis="in the page") for o in d["options"]])),
      expect="axis 'outside the page' has no option")

c.run("the full list freezes", 0, "freeze", save("run", listed), expect="frozen: 9 distinct options")
frozen = json.loads((c.folder / "run.json").read_text(encoding="utf-8"))
c.run("a frozen list that is not judged yet fails", 1, "check", "run.json", expect="not judged yet")

c.run("a fully judged list with two survivors passes", 0, "check", variant(frozen, "judged", judge), expect="RESULT pass")
c.run("three survivors pass", 0, "check", variant(frozen, "three", lambda d: judge(d, ("O-01", "O-04", "O-08"))))
c.run("one survivor fails", 1, "check", variant(frozen, "one", lambda d: judge(d, ("O-01",))), expect="1 survivors")
c.run("four survivors fail", 1, "check", variant(frozen, "four", lambda d: judge(d, ("O-01", "O-02", "O-04", "O-08"))), expect="4 survivors")
c.run("a rejection with no reason fails", 1, "check",
      variant(frozen, "noreason", lambda d: (judge(d), d["options"][2].pop("reason"))), expect="O-03: rejected with no reason")
c.run("a placeholder reason fails", 1, "check",
      variant(frozen, "tbdreason", lambda d: (judge(d), d["options"][2].update(reason="TBD, will explain later"))), expect="O-03: rejected with no reason")
c.run("a survivor with no basis fails", 1, "check",
      variant(frozen, "nobasis", lambda d: (judge(d), d["options"][0].pop("basis"))), expect="O-01: a survivor must state its basis")
c.run("a survivor whose basis points at a missing file fails", 1, "check",
      variant(frozen, "badwhere", lambda d: (judge(d), d["options"][0].update(where="src/gone.py"))), expect="was not found")
c.run("removing a cut option from the file fails", 1, "check",
      variant(frozen, "removed", lambda d: (judge(d), d["options"].pop(2))), expect="O-03: was in the frozen list and has been removed")
c.run("rewriting an option after the freeze fails", 1, "check",
      variant(frozen, "retitled", lambda d: (judge(d), d["options"][2].update(title="Something else entirely"))), expect="title changed after the freeze")
c.run("an option added after the freeze is noted and allowed", 0, "check",
      variant(frozen, "late", lambda d: (judge(d), d["options"].append(
          {"id": "O-10", "title": "Combine the button with the saved filter", "status": "rejected", "reason": "Two features at once for a first step."}))),
      expect="added after the freeze: O-10")
c.run("one reason pasted on every cut warns and still passes", 0, "check",
      variant(frozen, "samereason", lambda d: (judge(d), [o.update(reason="Not as strong as the others.") for o in d["options"] if o["status"] == "rejected"])),
      expect="same reason is given word for word")
c.write("broken.json", "[1, 2")
c.run("a file that is not JSON is blocked", 2, "check", "broken.json", expect="not valid JSON")
c.done()

"""Run spec's speclint.py on good and bad specs in a new folder and compare exit codes.

Usage: spec_cases.py <path to speclint.py> <new folder>
"""
import argparse

import casekit

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("script")
parser.add_argument("folder")
args = parser.parse_args()
c = casekit.Cases(args.script, args.folder, "spec")

GOOD = """# Spec: CSV export for the reports page

## Goal

The two accountants download the rows they see on the reports page as a CSV file, so the month-end check needs no copying by hand.

## Done when

- R-001: Clicking "Export" downloads a file named `reports-YYYY-MM-DD.csv`. Check: test: tests/test_export.py::test_file_name
- R-002: The file holds one line per row shown on screen after filtering, in the same order. Check: test: tests/test_export.py::test_rows_match_filter
- R-003: A report of 10,000 rows is written in under 2 seconds on the staging server.
  Check: measure: time of `python3 bench/export.py 10000`, limit 2 s
- R-004: With no rows on screen the button is disabled. Check: inspect: open the reports page with a filter that matches nothing

## Not doing

- Excel files.
- Scheduled exports.

## Open questions

- none
"""


def spec(name, text):
    return c.write(f"docs/specs/{name}.md", text).relative_to(c.folder)


c.run("no file is blocked", 2, "check", "docs/specs/missing.md", expect="does not exist")
c.run("template writes a skeleton", 0, "template", "docs/specs/skeleton.md", "--title", "Export")
c.run("template refuses to overwrite", 2, "template", "docs/specs/skeleton.md", "--title", "Export")
c.run("the untouched skeleton fails", 1, "check", "docs/specs/skeleton.md", expect="does not name its check")
c.run("a complete spec passes and reports the next id", 0, "check", spec("good", GOOD), expect="next free id R-005")
c.run("a continuation line is read as part of its bullet", 0, "check", spec("good2", GOOD), absent="R-003 does not name")

c.run("a missing 'Not doing' part fails", 1, "check",
      spec("nonot", GOOD.replace("## Not doing\n\n- Excel files.\n- Scheduled exports.\n\n", "")), expect="missing part '## Not doing'")
c.run("an empty 'Not doing' part fails", 1, "check",
      spec("emptynot", GOOD.replace("- Excel files.\n- Scheduled exports.\n", "")), expect="'## Not doing' is empty")
c.run("a repeated id fails", 1, "check", spec("dupe", GOOD.replace("- R-002:", "- R-001:")), expect="already used on line")
c.run("a bullet with no id fails", 1, "check",
      spec("noid", GOOD.replace("- R-004: With", "- With")), expect="not an id of the form R-001")
c.run("an id in another form fails", 1, "check", spec("badid", GOOD.replace("R-004", "REQ-4")), expect="not an id of the form R-001")
c.run("a line with no check fails", 1, "check",
      spec("nocheck", GOOD.replace(" Check: inspect: open the reports page with a filter that matches nothing", "")), expect="R-004 does not name its check")
c.run("an unknown check method fails", 1, "check", spec("badmethod", GOOD.replace("Check: inspect:", "Check: vibes:")), expect="check method 'vibes'")
c.run("a method with no 'how' fails", 1, "check",
      spec("nohow", GOOD.replace("Check: inspect: open the reports page with a filter that matches nothing", "Check: inspect")), expect="and not how")
c.run("a vague word fails", 1, "check",
      spec("vague", GOOD.replace("is written in under 2 seconds on the staging server", "is written quickly")), expect="uses 'quickly'")
c.run("an open-ended phrase fails", 1, "check",
      spec("etc", GOOD.replace("in the same order.", "in the same order, with totals etc.")), expect="uses 'etc'")
c.run("a vague word inside backticks or quotes is a name, not prose", 0, "check",
      spec("quoted", GOOD.replace('Clicking "Export"', 'Clicking "Fast export" in the `simple` layout')))
c.run("a placeholder fails", 1, "check", spec("placeholder", GOOD.replace("- Scheduled exports.", "- TBD")), expect="placeholder 'TBD'")
c.run("an angle-bracket placeholder fails", 1, "check",
      spec("angle", GOOD.replace("CSV export for the reports page", "<feature name>")), expect="placeholder '<feature name>'")
c.run("an open question fails", 1, "check",
      spec("open", GOOD.replace("- none", "- Comma or semicolon as separator?")), expect="open question left")
c.run("'and' in a statement warns and still passes", 0, "check",
      spec("compound", GOOD.replace("With no rows on screen the button is disabled.", "With no rows on screen the button is disabled and a hint is shown.")),
      expect="joins two things with 'and'")
c.run("a long spec warns and still passes", 0, "check", spec("long", GOOD + "\n" * 90), expect="one page is about 80")

# Second mode: a spec written from existing code.
c.write("src/app.py", "from flask import Flask\napp = Flask(__name__)\n\n@app.get('/reports')\ndef reports():\n    return []\n\n@app.post('/reports/export')\ndef export():\n    return 'a,b'\n")
c.write("src/admin.py", "import argparse\np = argparse.ArgumentParser()\ns = p.add_subparsers()\ns.add_parser('purge')\n")
c.write("tests/test_app.py", "def test_reports_lists_rows():\n    assert True\n")
FROM_CODE = """# Spec: what the reports service does today

## Goal

Record the behaviour the code has now, so later changes can be traced.

## Done when

- R-001: `GET /reports` returns the list of report rows as JSON. Check: test: tests/test_app.py::test_reports_lists_rows Source: src/app.py:4
- R-002: `POST /reports/export` returns the rows as comma-separated text. Check: demo: post to the route with curl on the local server Source: src/app.py:8, tests/test_app.py

## Not doing

- Behaviour that is not in the code today.
"""
c.run("survey lists routes, commands and tests with file and line", 0, "survey", expect="src/app.py:8")
c.run("survey finds the test", 0, "survey", expect="tests/test_app.py:1")
c.run("a spec from code with sources passes, and warns about the uncited command file", 0, "check", "--from-code",
      spec("fromcode", FROM_CODE), expect="src/admin.py")
c.run("the same spec without --from-code also passes", 0, "check", spec("fromcode2", FROM_CODE))
c.run("a line with no source fails in --from-code", 1, "check", "--from-code",
      spec("nosource", FROM_CODE.replace(" Source: src/app.py:4", "")), expect="R-001 cites no file")
c.run("a source file that does not exist fails", 1, "check", "--from-code",
      spec("ghost", FROM_CODE.replace("src/app.py:4", "src/gone.py:4")), expect="is not a file under")
c.run("a source line past the end of the file fails", 1, "check", "--from-code",
      spec("pastend", FROM_CODE.replace("src/app.py:4", "src/app.py:400")), expect="which has 10 lines")
c.run("a source outside the project fails", 1, "check", "--from-code",
      spec("outside", FROM_CODE.replace("src/app.py:4", "../casekit.py")), expect="is not a file under")
c.write("empty/readme.txt", "nothing here\n")
c.run("survey of a folder with no code is not verified", 2, "--root", "empty", "survey", expect="RESULT not verified")
c.done()

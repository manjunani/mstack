"""Build a small git project with a spec, tests, code and commits, then check trace.py raises each of its four flags.

Usage: trace_cases.py <path to trace.py> <new folder>
"""
import argparse
import json
import os
import subprocess

import casekit

GIT = "/usr/bin/git"

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("script")
parser.add_argument("folder")
args = parser.parse_args()
c = casekit.Cases(args.script, args.folder, "trace")
repo = c.folder / "repo"


def git(*arguments):
    subprocess.run([GIT, "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *arguments], check=True, capture_output=True)


def commit(message):
    git("add", "-A")
    git("commit", "-qm", message)


SPEC = """# Spec: CSV export

## Goal

Accountants download the rows they see.

## Done when

- R-001: The file is named `reports-YYYY-MM-DD.csv`. Check: test: tests/test_export.py
- R-002: The file holds the rows shown on screen. Check: test: tests/test_export.py
- R-003: 10,000 rows are written in under 2 seconds.
  Check: measure: bench/export.py, limit 2 s
- R-004: An empty report gives a file with the header line only. Check: test: tests/test_export.py
- R-005: The separator is a comma. Check: test: tests/test_export.py
- R-007: The file is UTF-8 with a byte order mark. Check: test: tests/test_export.py

## Not doing

- Excel files.
"""

repo.mkdir()
c.run("no spec is blocked", 2, "--root", "repo", "matrix", expect="no spec found")
c.run("a named spec that does not exist is blocked", 2, "--root", "repo", "--spec", "docs/nope.md", "matrix", expect="spec not found")
(repo / "docs" / "specs").mkdir(parents=True)
subprocess.run([GIT, "init", "-q", str(repo)], check=True, capture_output=True)
c.write("repo/docs/specs/export.md", "# Spec: CSV export\n\n## Done when\n\n- The file is named well.\n")
c.run("a spec with no ids is blocked", 2, "--root", "repo", "matrix", expect="no requirement id")

c.write("repo/docs/specs/export.md", SPEC)
c.write("repo/src/export.py", "# R-001: file name carries the date\ndef name():\n    return 'reports.csv'\n")
c.write("repo/tests/test_export.py", "def test_file_name():  # R-001\n    assert True\n")
commit("first: spec and file name")
c.write("repo/src/export.py", "# R-001: file name carries the date\ndef name():\n    return 'reports.csv'\n\ndef rows(shown):\n    return shown\n")
c.write("repo/tests/test_export.py",
        "def test_file_name():  # R-001\n    assert True\n\ndef test_r_002_rows_match_filter():\n    assert True\n\n"
        "def test_separator():\n    # R-005\n    assert True\n\ndef test_old_idea():  # R-009\n    assert True\n")
commit("R-002: rows follow the filter")
c.write("repo/src/bench.py", "# R-003 timing harness\n# R-004 empty report\n# R-007 byte order mark\n")
commit("timing harness")
c.write("repo/tests/test_export.py",
        "def test_file_name():  # R-001\n    assert True\n\ndef test_r_002_rows_match_filter():\n    assert True\n\n"
        "def test_separator():\n    # R-005\n    assert True\n\ndef test_old_idea():  # R-009\n    assert True\n\ndef test_more():\n    assert True\n")
commit("R-005: test only, no source file changed")
c.write("repo/docs/specs/export.md", SPEC.replace("- R-007: The file is UTF-8 with a byte order mark. Check: test: tests/test_export.py\n", ""))
commit("drop the byte order mark requirement; also mentions R-012 in passing")

out = c.run("the four flags are raised", 1, "--root", "repo", "matrix", expect="RESULT fail: 4 flag(s)")
c.check("no-test is raised for R-004, which has code and no test", "no-test      R-004" in out)
c.check("no-code is raised for R-005: its only commit changed a test file", "no-code      R-005" in out)
c.check("orphan-test is raised for R-009 and says it was never in the spec", "orphan-test  R-009" in out and "never in the spec" in out)
c.check("gone is raised for R-007 and says it used to be in the spec", "gone         R-007" in out and "was in docs/specs/export.md" in out)
c.check("R-002 is covered by a test name written r_002 and by a commit", "no-test      R-002" not in out and "no-code      R-002" not in out)
c.check("R-003 needs no test because its check is 'measure' on a continuation line", "R-003: no test, and none expected" in out)
c.check("an id seen only in commit history is a note, not a flag", "note  R-012: appears only in commit history" in out)
matrix = json.loads((repo / ".mstack" / "trace" / "matrix.json").read_text(encoding="utf-8"))
c.check("matrix.json holds five rows", len(matrix["rows"]) == 5)
c.check("matrix.md was written", (repo / ".mstack" / "trace" / "matrix.md").is_file())

c.run("a waiver with no real reason is refused", 2, "--root", "repo", "waive", "R-004", "--flag", "no-test", "--reason", "todo later", expect="real reason")
c.run("a waiver for an unknown id is refused", 2, "--root", "repo", "waive", "R-099", "--flag", "no-test",
      "--reason", "Covered by the manual release checklist.", expect="not defined")
c.run("orphan-test cannot be waived", 2, "--root", "repo", "waive", "R-004", "--flag", "orphan-test",
      "--reason", "Covered by the manual release checklist.", expect="can be waived")
c.run("a waiver with a reason is saved", 0, "--root", "repo", "waive", "R-004", "--flag", "no-test",
      "--reason", "Checked by hand in the release checklist until the page has a test harness.")
c.run("the waived flag no longer counts", 1, "--root", "repo", "matrix", expect="RESULT fail: 3 flag(s)")

# Repair the rest: fix the orphan and gone ids, give R-005 a code reference.
c.write("repo/src/bench.py", "# R-003 timing harness\n# R-004 empty report\n")
c.write("repo/src/export.py", "# R-001: file name carries the date\ndef name():\n    return 'reports.csv'\n\ndef rows(shown):\n    return shown\n\nSEPARATOR = ','  # R-005\n")
c.write("repo/tests/test_export.py",
        "def test_file_name():  # R-001\n    assert True\n\ndef test_r_002_rows_match_filter():\n    assert True\n\n"
        "def test_separator():\n    # R-005\n    assert True\n\ndef test_r_004_empty():\n    assert True\n")
c.run("after the repairs the matrix passes, and the unused waiver is reported", 0, "--root", "repo", "matrix", expect="no longer applies")

# The same files outside git. The ceiling stops git from finding a repository that holds the test folder itself.
os.environ["GIT_CEILING_DIRECTORIES"] = str(c.folder)
plain = c.folder / "plain"
for path in ("docs/specs/export.md", "src/export.py", "src/bench.py", "tests/test_export.py"):
    c.write(f"plain/{path}", (repo / path).read_text(encoding="utf-8"))
c.run("without git, 'no-code' for R-002 is undecided and the result is not verified, not a fail", 2, "--root", "plain", "matrix",
      expect="'no-code' is undecided for R-002")
c.run("with --no-commits the file-only matrix is accepted and R-002 lacks code", 1, "--root", "plain", "matrix", "--no-commits", expect="no-code      R-002")
c.write("plain/src/export.py", (plain / "src" / "export.py").read_text(encoding="utf-8") + "# R-002 rows\n")
c.run("with every id in a file, --no-commits passes", 0, "--root", "plain", "matrix", "--no-commits", expect="RESULT pass")
c.write("plain/docs/specs/second.md", "# Spec: other\n\n## Done when\n\n- R-001: A second definition. Check: demo: none\n")
c.run("an id defined in two specs is flagged", 1, "--root", "plain", "matrix", "--no-commits", expect="repeated-id")
c.done()

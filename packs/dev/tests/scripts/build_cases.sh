#!/bin/sh
# Script test for the build skill: ledger.py through a two-task plan, with a failing check, files outside the
# list, a check that runs no tests, the end-of-build suite and review, and the per-task review mode.
# Arguments: path to packs/dev, path of a NEW folder for the throwaway project (outside temporary folders).
DEV=$(cd "$1" && pwd); P="$2"; NAME=build
. "$DEV/tests/scripts/lib.sh"
L="$DEV/skills/build/scripts/ledger.py"; FX="$DEV/tests/scripts/fixtures"
new_project "$P"
mkdir -p src tests docs .mstack/plans
printf 'def sub(a, b):\n    return a - b\n' > src/calc.py
echo "notes" > docs/notes.md
cp "$FX/build_plan.md" .mstack/plans/calc.md
$G add src docs && $GC commit -qm "calc base"
PLAN=.mstack/plans/calc.md

t 0 "help prints" python3 "$L" --help
t 2 "status with no ledger is not verified" python3 "$L" status
t 2 "done before any start is blocked" python3 "$L" done 1
t 2 "start for a task the plan lacks is blocked" python3 "$L" start 9 --plan "$PLAN"
t 0 "brief prints task 2 as a standalone brief" python3 "$L" brief 2 --plan "$PLAN"
has "# Brief: task 2 of 2: Command line"
has "Goal: The calculator adds and has a command line."
has "1. src/cli.py reads two numbers and prints their sum."
has "Touch only these files: src/cli.py."
has "Run the check until it prints what Expect says: \`python3 src/cli.py 2 3\`"
has "STATUS: done | failed | blocked"
hasnt "Add numbers"
t 0 "brief for task 1 names the later task as not its own" python3 "$L" brief 1 --plan "$PLAN"
has "Later tasks (2) are not yours"
t 2 "brief for a task the plan lacks is blocked" python3 "$L" brief 9 --plan "$PLAN"
t 2 "brief with no plan and no ledger is blocked" python3 "$L" brief 1
same "brief wrote nothing" "$(ls .mstack)" "plans"
t 0 "start task 1 from the plan" python3 "$L" start 1 --plan "$PLAN"
has "files: src/calc.py, tests/test_calc.py, tests/__init__.py"
has "check: python3 -m unittest tests.test_calc"
t 0 "brief with no --plan reads the plan from the ledger" python3 "$L" brief 2
has "# Brief: task 2 of 2: Command line"
t 2 "start task 2 while task 1 is open is blocked" python3 "$L" start 2 --plan "$PLAN"
t 2 "starting task 1 twice is blocked" python3 "$L" start 1 --plan "$PLAN"

t 1 "done fails while the task's test does not pass" python3 "$L" done 1
has "is not logged as complete"

printf 'def sub(a, b):\n    return a - b\n\n\ndef add(a, b):\n    return a + b\n' > src/calc.py
: > tests/__init__.py
printf 'import unittest\nfrom src.calc import add\n\n\nclass T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n' > tests/test_calc.py
echo "stray edit" >> README.md
t 1 "done fails when a file outside the list changed" python3 "$L" done 1
has "outside: README.md"
t 2 "accepting outside files needs a real reason" python3 "$L" done 1 --accept-outside "ok"
$G checkout -q README.md
t 0 "done logs completion when the check passes and the files fit" python3 "$L" done 1
has "task 1 logged as complete"
t 2 "done twice is blocked" python3 "$L" done 1
$G add src tests && $GC commit -qm "add numbers"

echo "private note, not part of any task" >> docs/notes.md
t 0 "start task 2 with a file that was already dirty" python3 "$L" start 2 --plan "$PLAN"
has "1 files were already changed before this task"
printf 'import sys\nsys.path.insert(0, ".")\nfrom src.calc import add\nprint(add(int(sys.argv[1]), int(sys.argv[2])))\n' > src/cli.py
t 2 "finish before every task is done is not verified" python3 "$L" finish --suite "python3 -m unittest discover -s tests -t ."
has "tasks without a completion line: 2"
t 0 "done task 2: the earlier dirty file is not counted" python3 "$L" done 2
hasnt "outside:"
$G add src && $GC commit -qm "command line"

t 1 "finish with a failing suite fails" python3 "$L" finish --suite "python3 -c 'import sys; print(\"1 failed\"); sys.exit(3)'"
t 1 "status reports the failed suite" python3 "$L" status
t 1 "a suite that runs no tests fails" python3 "$L" finish --suite "echo collected 0 items"
has "ran no tests"
t 2 "a suite command that does not exist is not verified" python3 "$L" finish --suite "no-such-test-runner-xyz"
t 0 "finish with the real suite passes" python3 "$L" finish --suite "python3 -m unittest discover -s tests -t ."
has "next: one review of the range"
t 2 "status without a review is not verified" python3 "$L" status
has "no review recorded"
t 2 "recording a review needs a findings file" python3 "$L" reviewed --findings .mstack/none.json
echo '{"findings": [], "not_judged": ["performance"]}' > .mstack/findings.json
t 0 "review recorded" python3 "$L" reviewed --findings .mstack/findings.json
t 0 "status passes: tasks done, suite green, review recorded" python3 "$L" status
has "RESULT pass"

echo "# later change" >> src/cli.py && $G add src && $GC commit -qm "late change"
t 2 "status goes back to not verified when the code changes after the suite" python3 "$L" status
has "the code changed after the last suite run"

t 0 "a task without a plan file: --files and --check" python3 "$L" start a --name adhoc --files "src/" --check "echo collected 0 items"
t 1 "a check that ran no tests does not count" python3 "$L" done a --name adhoc
has "the check ran no tests"
t 0 "restart records a new start" python3 "$L" start a --name adhoc --files "src/" --check "no-such-test-runner-xyz" --restart
t 2 "a check that cannot run is not verified" python3 "$L" done a --name adhoc
t 2 "a task needs files and a check" python3 "$L" start b --name other

t 0 "per-task review: start task 1" python3 "$L" start 1 --name strict --review per-task --files "docs/" --check "test -f docs/notes.md"
t 0 "per-task review: done task 1" python3 "$L" done 1 --name strict
has "review this task now"
t 2 "per-task review: task 2 may not start before task 1 is reviewed" python3 "$L" start 2 --name strict --files "docs/" --check "test -f docs/notes.md"
has "task 1 has no review yet"
t 0 "per-task review: review recorded for task 1" python3 "$L" reviewed --name strict --task 1 --findings .mstack/findings.json
t 0 "per-task review: task 2 may start now" python3 "$L" start 2 --name strict --files "docs/" --check "test -f docs/notes.md"

same "the ledger folder is git-ignored" "$($G status --porcelain --ignored .mstack/build | cut -c1-2)" "!!"
mkdir "$P.nogit" && cd "$P.nogit" || exit 9
t 2 "outside a git repository is blocked" python3 "$L" status
finish

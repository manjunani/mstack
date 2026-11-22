#!/bin/sh
# Script test for the plan skill: plan_lint.py on a good plan, a bad plan, a plan far longer than its spec, and bad input.
# Arguments: path to packs/dev, path of a NEW folder for the throwaway project (outside temporary folders).
DEV=$(cd "$1" && pwd); P="$2"; NAME=plan
. "$DEV/tests/scripts/lib.sh"
L="$DEV/skills/plan/scripts/plan_lint.py"; FX="$DEV/tests/scripts/fixtures"
new_project "$P"
mkdir -p src tests docs .mstack/plans
printf 'def read_header(path):\n    return open(path).readline()\n' > src/dates.py
printf 'def main():\n    pass\n' > src/report.py
echo "Reports show the date from the file header in ISO form, as YYYY-MM-DD. A header with no date is an error the user sees. Nothing else in the report changes and no other module is touched by this work at all." > docs/spec.md
cp "$FX/plan_good.md" "$FX/plan_bad.md" "$FX/plan_long.md" "$FX/plan_notaplan.md" .mstack/plans/

t 0 "help prints" python3 "$L" --help
has "Exit codes"

t 0 "good plan passes" python3 "$L" lint .mstack/plans/plan_good.md
has "RESULT pass"
has "tasks: 2"

t 1 "bad plan fails" python3 "$L" lint .mstack/plans/plan_bad.md
has "task numbers are [1, 3, 4]"
has "src/nowhere.py does not exist"
has "Expect 'works' cannot be compared"
has "filler 'handle edge cases'"
has "filler 'TODO'"
has "'various' is not a file path"
has "Check is not a command"
has "task 4 has no Files"
has "task 4 has no Check"
has "uses \`format_day\`, which task 4 makes later"
has "uses \`parse-date\`, but the plan makes \`parse_date\`"
has "uses \`read_headers\`: no earlier task makes it and it is not in the project"
has "writes \`parseDate\`, but task 1 makes \`parse_date\`"
has "Spec: docs/missing-spec.md does not exist"
has "RESULT fail"

t 0 "plan much longer than its spec passes with a warning" python3 "$L" lint .mstack/plans/plan_long.md
has "more than 3 times longer"
has "not a measured value"

t 2 "a file that is not a plan is blocked" python3 "$L" lint .mstack/plans/plan_notaplan.md
has "RESULT blocked"
t 2 "a missing file is blocked" python3 "$L" lint .mstack/plans/nope.md
t 2 "no command given" python3 "$L"

t 0 "tasks prints JSON" python3 "$L" tasks .mstack/plans/plan_good.md
has '"check": "python3 -m unittest tests.test_report -v"'
has '"tests/test_report.py"'

t 1 "paths are judged against --root, not the current folder" python3 "$L" lint .mstack/plans/plan_good.md --root docs
has "src/dates.py does not exist"

same "lint wrote nothing: git sees only the new sample files" "$($G status --porcelain | sort | tr '\n' ' ')" "?? .mstack/ ?? docs/ ?? src/ "
finish

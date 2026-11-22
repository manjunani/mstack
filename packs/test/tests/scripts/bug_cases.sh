#!/bin/sh
# Exercise the bug-report script in a throwaway project.
# Arguments: path to packs/test, path of a NEW folder to create (outside temporary folders).
PACK=$(cd "$1" && pwd); P="$2"
[ -e "$P" ] && { echo "refusing: $P already exists"; exit 9; }
. "$PACK/tests/scripts/lib.sh"
B="$PACK/skills/bug-report/scripts/bugrep.py"
mkdir -p "$P" && cd "$P" || exit 9

cat > app.py <<'EOF'
import json, pathlib, sys
state = pathlib.Path("state.json")
cart = json.loads(state.read_text()) if state.exists() else {}
print(cart["total"])
EOF
cat > fixed.py <<'EOF'
print(0)
EOF
cat > sometimes.py <<'EOF'
import pathlib
p = pathlib.Path(".n"); n = int(p.read_text()) + 1 if p.exists() else 1; p.write_text(str(n))
if n % 2: raise SystemExit("boom: odd run")
EOF

echo "#### repro"
t 2 "no marker given" python3 "$B" repro --id cart --command "python3 app.py"
t 0 "reproduced from a clean start, twice" python3 "$B" repro --id cart --clean "python3 -c \"import pathlib; pathlib.Path('state.json').unlink(missing_ok=True)\"" --command "python3 app.py" --expect "KeyError: 'total'" --runs 2
has "reproduced on 2 of 2" "counts the runs"
t 0 "the output was saved as evidence" grep -q "KeyError: 'total'" .mstack/bugs/cart/run-1.log
t 0 "the record says reproduced" grep -q '"result": "reproduced"' .mstack/bugs/cart/repro.json
t 1 "a fixed program does not reproduce" python3 "$B" repro --id cart --command "python3 fixed.py" --expect "KeyError"
t 0 "the first evidence folder was kept; a new one was made" test -d .mstack/bugs/cart-2
t 1 "a different failure is not this bug" python3 "$B" repro --id other --command "python3 nope.py" --expect "KeyError: 'total'"
t 2 "half the runs: intermittent, not verified" python3 "$B" repro --id flaky --command "python3 sometimes.py" --expect "boom" --runs 4
has "2 of 4" "counts the hits"
t 2 "a failing clean step stops the run" python3 "$B" repro --id c --clean "python3 -c 'import sys; sys.exit(3)'" --command "python3 app.py" --expect KeyError
t 2 "a command that cannot start" python3 "$B" repro --id x --command "no-such-tool-xyz --go" --expect KeyError
t 0 "expected exit code as the marker" python3 "$B" repro --id code --command "python3 app.py" --expect-exit 1

echo "#### lint"
mkdir -p reports
cp .mstack/bugs/cart/run-1.log reports/run-1.log
cat > reports/good.md <<'EOF'
# Cart total crashes on an empty cart

## Summary
Opening the cart with no saved state crashes with KeyError.

## Steps to reproduce
1. Remove state.json.
2. Run `python3 app.py`.

## Expected
It prints 0.

## Actual
It exits with KeyError: 'total'.

## Environment
Python 3.14 on macOS; app commit unknown. Reporter account: qa@example.com.

## Evidence
- `run-1.log`
EOF
t 0 "a complete report passes" python3 "$B" lint reports/good.md
python3 - <<'EOF'
import pathlib
good = pathlib.Path("reports/good.md").read_text()
tok = "gh" + "p_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
mail = "jo" + "@" + "gma" + "il.com"
bad = good.replace("## Environment\n", "## Environment\nToken used: " + tok + "\nUser " + mail + "\n")
bad = bad.replace("1. Remove state.json.\n2. Run `python3 app.py`.", "remove state and run it")
bad = bad.replace("It exits with KeyError: 'total'.", "It prints 0.")
bad = bad.replace("- `run-1.log`", "- `missing.log`")
bad = bad.replace("## Summary\nOpening the cart with no saved state crashes with KeyError.\n", "")
pathlib.Path("reports/bad.md").write_text(bad)
EOF
t 1 "a report with faults fails" python3 "$B" lint reports/bad.md
has "missing section: summary" "summary is required"
has "steps to reproduce are not a numbered list" "steps are numbered"
has "expected and actual say the same thing" "no defect described"
has "evidence file not found: missing.log" "evidence exists"
has "GitHub token in bad.md" "secret found"
has "email address in bad.md" "personal email found"
lacks "a1B2c3" "the token itself is not printed"
: > reports/empty.log
sed 's/run-1.log/empty.log/' reports/good.md > reports/emptyev.md
t 1 "empty evidence file" python3 "$B" lint reports/emptyev.md
t 2 "no report file" python3 "$B" lint reports/none.md

finish

#!/bin/sh
# Script test for the prove-test skill: prove.py on a real fix, a test that proves nothing, a fix already
# committed, a new file, a staged change, a hang, an interrupt and a hard kill. After every case the
# working files must be exactly as before.
# Arguments: path to packs/dev, path of a NEW folder for the throwaway project (outside temporary folders).
DEV=$(cd "$1" && pwd); P="$2"; NAME=prove-test
. "$DEV/tests/scripts/lib.sh"
V="$DEV/skills/prove-test/scripts/prove.py"; FX="$DEV/tests/scripts/fixtures"
new_project "$P"
mkdir -p src tests
: > src/__init__.py
printf 'def add(a, b):\n    return a - b\n' > src/calc.py
$G add src && $GC commit -qm "calc with a bug"
sum() { shasum -a 256 "$1" | cut -d' ' -f1; }
TEST="python3 -m unittest tests.test_calc"

t 0 "help prints" python3 "$V" --help
t 2 "status before any proof is not verified" python3 "$V" status
t 2 "nothing changed: blocked, nothing to put aside" python3 "$V" run --test "true"

# the fix (not committed) and a new test file (not tracked)
printf 'def add(a, b):\n    return a + b\n' > src/calc.py
: > tests/__init__.py
printf 'import unittest\nfrom src.calc import add\n\n\nclass T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5, "sum is wrong")\n' > tests/test_calc.py
FIXED=$(sum src/calc.py); STATUS=$($G status --porcelain -uall)

t 0 "a real fix with a real test is proven" python3 "$V" run --test "$TEST"
has "exit codes 0, 1, 0"
has "the change (1 files"
has "kept in place: tests/__init__.py, tests/test_calc.py"
same "the fix is back, byte for byte" "$(sum src/calc.py)" "$FIXED"
same "git sees the same tree as before" "$($G status --porcelain -uall)" "$STATUS"
t 0 "status shows the proof" python3 "$V" status

t 1 "a test that passes without the fix proves nothing" python3 "$V" run --test "python3 -c 'print(1)'"
has "passes without the change"
same "the fix is back after the failed proof" "$(sum src/calc.py)" "$FIXED"

t 1 "a test that fails with the fix stops before anything is put aside" python3 "$V" run --test "python3 -c 'import sys; sys.exit(4)'"
has "nothing was put aside"
t 2 "a test command that does not exist is not verified" python3 "$V" run --test "no-such-runner-xyz"

t 0 "the failing run shows the expected symptom" python3 "$V" run --test "$TEST" --expect-text "sum is wrong"
t 1 "a failure with other text does not count" python3 "$V" run --test "$TEST" --expect-text "division by zero"
has "fails for another reason"

# tracked Python bytecode that a test run rewrites is not a change to put back
mkdir -p src/__pycache__ && printf 'old' > src/__pycache__/calc.cpython-3.pyc
$G add -f src/__pycache__ && $GC commit -qm "tracked bytecode" src/__pycache__
t 0 "a test run that rewrites tracked bytecode still restores" python3 "$V" run --test "printf x >> src/__pycache__/calc.cpython-3.pyc; $TEST"
has "restored: all 1 files are back"
$G rm -rqf --cached src/__pycache__ && rm -rf src/__pycache__ && $GC commit -qm "drop bytecode"

t 2 "--fix on a path with no change is blocked" python3 "$V" run --test "$TEST" --fix README.md
t 2 "--against a name that is no commit is blocked" python3 "$V" run --test "$TEST" --against no-such-ref
t 0 "--fix names the change" python3 "$V" run --test "$TEST" --fix src/calc.py

# same-size change made in the same second: each run must still see a file with a new modification time
cp "$FX/prove_mtime.py" tests/mtime_helper.py
printf 'def add(a, b):\n    return a + b\n' > src/calc.py
t 0 "a same-size change is proven right after it was written" python3 "$V" run --test "python3 tests/mtime_helper.py .mstack/mtimes.log" --keep tests/mtime_helper.py
same "the three runs saw three different modification seconds" "$(sort -u .mstack/mtimes.log | wc -l | tr -d ' ')" "3"

# a staged change stays staged
$G add src/calc.py; STAGED=$($G diff --cached | shasum | cut -d' ' -f1)
t 0 "a staged fix is proven" python3 "$V" run --test "$TEST"
same "the index is untouched" "$($G diff --cached | shasum | cut -d' ' -f1)" "$STAGED"

# the change includes a new file that is not tracked
printf 'def plus(a, b):\n    return a + b\n' > src/helper.py
printf 'from src.helper import plus\n\n\ndef add(a, b):\n    return plus(a, b)\n' > src/calc.py
HELPER=$(sum src/helper.py); FIXED=$(sum src/calc.py)
t 0 "a new untracked file is put aside and brought back" python3 "$V" run --test "$TEST"
has "src/calc.py, src/helper.py"
same "the new file is back" "$(sum src/helper.py)" "$HELPER"
same "the changed file is back" "$(sum src/calc.py)" "$FIXED"

# a hang, an interrupt and a hard kill during the middle run
HANG="python3 -c \"import sys, time; sys.path.insert(0, '.'); from src.calc import add; time.sleep(0 if add(2, 3) == 5 else 30)\""
t 2 "a hang without the change is not verified, and the files come back" python3 "$V" run --test "$HANG" --timeout 3
has "restored: all 2 files are back"
same "the changed file is back after the hang" "$(sum src/calc.py)" "$FIXED"

cp "$FX/prove_killer.py" tests/killer_helper.py
t 2 "SIGTERM during the middle run: files are put back, result is not verified" python3 "$V" run --test "python3 tests/killer_helper.py TERM" --keep tests/killer_helper.py
has "the files were put back"
same "the changed file is back after SIGTERM" "$(sum src/calc.py)" "$FIXED"
same "the new file is back after SIGTERM" "$(sum src/helper.py)" "$HELPER"

t 137 "SIGKILL during the middle run: the script dies" python3 "$V" run --test "python3 tests/killer_helper.py KILL" --keep tests/killer_helper.py
same "after the kill the new file really is missing (the crash is real)" "$(test -e src/helper.py && echo present || echo missing)" "missing"
t 2 "a new run refuses while files are still put aside" python3 "$V" run --test "$TEST"
has "prove.py restore"
t 2 "status says so too" python3 "$V" status
t 0 "restore puts the files back from the journal" python3 "$V" restore
same "the changed file is back after the kill" "$(sum src/calc.py)" "$FIXED"
same "the new file is back after the kill" "$(sum src/helper.py)" "$HELPER"
t 0 "restore with nothing pending is a pass" python3 "$V" restore
has "nothing to restore"

# a fix that is already committed
$G add src tests && $GC commit -qm "fix add"
t 2 "committed fix, default comparison: nothing to put aside" python3 "$V" run --test "$TEST"
has "--against"
t 0 "committed fix, compared with the commit before it" python3 "$V" run --test "$TEST" --against HEAD~1
same "the tree is clean after proving a committed fix" "$($G status --porcelain -- . ':(exclude).mstack')" ""
echo "# touched" >> src/calc.py
t 2 "status: the proof is stale once a proven file changes" python3 "$V" status
has "changed after that proof"

same "the proof folder is git-ignored" "$($G status --porcelain --ignored .mstack/prove | cut -c1-2)" "!!"
mkdir "$P.nogit" && cd "$P.nogit" || exit 9
t 2 "outside a git repository is blocked" python3 "$V" run --test "true"
finish

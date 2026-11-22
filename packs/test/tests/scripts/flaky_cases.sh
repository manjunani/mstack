#!/bin/sh
# Exercise the flaky-triage script in a throwaway project.
# Arguments: path to packs/test, path of a NEW folder to create the project in (outside temporary folders).
PACK=$(cd "$1" && pwd); P="$2"
[ -e "$P" ] && { echo "refusing: $P already exists"; exit 9; }
. "$PACK/tests/scripts/lib.sh"
R="$PACK/skills/flaky-triage/scripts/repeat.py"
mkdir -p "$P/tests" && cd "$P" || exit 9
git=/usr/bin/git

# A test that fails on every third run (a counter file stands in for timing), so the rate is known: 1 in 3.
cat > tests/__init__.py <<'EOF'
EOF
cat > shared.py <<'EOF'
SETTINGS = {}
EOF
cat > tests/test_counter.py <<'EOF'
import pathlib
import unittest


class CounterTest(unittest.TestCase):
    def test_every_third_run_fails(self):
        path = pathlib.Path(".counter")
        n = int(path.read_text()) + 1 if path.exists() else 1
        path.write_text(str(n))
        self.assertNotEqual(n % 3, 0, "simulated intermittent failure")
EOF
# Order dependence: test_b leaves a setting behind, test_victim assumes the default.
cat > tests/test_a.py <<'EOF'
import unittest


class A(unittest.TestCase):
    def test_a(self):
        self.assertTrue(True)
EOF
cat > tests/test_b.py <<'EOF'
import unittest
import shared


class B(unittest.TestCase):
    def test_sets_language(self):
        shared.SETTINGS["lang"] = "de"
        self.assertEqual(shared.SETTINGS["lang"], "de")
EOF
cat > tests/test_c.py <<'EOF'
import unittest


class C(unittest.TestCase):
    def test_c(self):
        self.assertEqual(1 + 1, 2)
EOF
cat > tests/test_d.py <<'EOF'
import unittest


class D(unittest.TestCase):
    def test_d(self):
        self.assertIn("a", "abc")
EOF
cat > tests/test_victim.py <<'EOF'
import unittest
import shared


class Victim(unittest.TestCase):
    def test_default_language(self):
        self.assertEqual(shared.SETTINGS.get("lang", "en"), "en")
EOF
# A stand-in for a runner with a seed option: it fails when the seed is divisible by 3.
cat > seeded.py <<'EOF'
import argparse
import sys

parser = argparse.ArgumentParser()
parser.add_argument("--order-seed", type=int, required=True)
seed = parser.parse_args().order_seed
print(f"order seed {seed}")
sys.exit(1 if seed % 3 == 0 else 0)
EOF
printf '.counter\n__pycache__/\n' > .gitignore
$git init -q -b main && $git add -A && $git -c user.name=t -c user.email=t@t commit -qm first

echo "#### guard on a clean tree"
t 2 "empty diff: nothing to scan" python3 "$R" guard

echo "#### run"
t 2 "no command" python3 "$R" run --times 3
t 2 "one run is refused" python3 "$R" run --times 1 -- python3 -c "pass"
t 2 "program not found" python3 "$R" run --times 2 -- no-such-runner-xyz
t 2 "seed flag without {seed}" python3 "$R" run --times 2 --seed-flag "--order-seed 5" -- python3 seeded.py
t 1 "12 runs of the intermittent test: 4 fail" python3 "$R" run --times 12 --label alone -- python3 -m unittest tests.test_counter
has "failed: 4" "the count is measured"
has "failure rate: 33.3%" "the rate is computed"
BEFORE=$(ls .mstack/flaky/alone-*.jsonl | head -1)
t 0 "the record has a header and 12 run lines with status, seconds and seed" python3 -c "
import json,sys
rows=[json.loads(l) for l in open('$BEFORE')]
assert rows[0]['header'] and len(rows)==13
assert all(set(['run','status','exit_code','seconds','seed','timed_out']) <= set(r) for r in rows[1:])
assert [r['run'] for r in rows[1:] if r['status']=='fail']==[3,6,9,12]
"
t 0 "the output of a failing run was saved" sh -c "grep -q 'simulated intermittent failure' .mstack/flaky/alone-*-run3.log"
t 1 "a test that fails every time is called broken, not flaky" python3 "$R" run --times 3 --label broken -- python3 -c "import sys; sys.exit(1)"
has "broken test, not an intermittent one" "says so"
t 0 "a stable command passes 5 of 5" python3 "$R" run --times 5 --label stable -- python3 -m unittest tests.test_a
t 1 "a run over the time limit counts as a failure" python3 "$R" run --times 2 --timeout 1 --label slow -- python3 -c "import time; time.sleep(5)"
has "TIMED OUT" "marked as timed out"
t 1 "seed flag: a new seed per run, failures follow the seed" python3 "$R" run --times 12 --label shuffled --base-seed 7 --seed-flag "--order-seed {seed}" -- python3 seeded.py
has "seeds of failing runs" "failing seeds are listed"
SEEDED=$(ls .mstack/flaky/shuffled-*.jsonl | head -1)
t 0 "every recorded seed explains its result" python3 -c "
import json
rows=[json.loads(l) for l in open('$SEEDED')][1:]
assert len({r['seed'] for r in rows})==12
assert all((r['seed']%3==0)==(r['status']=='fail') for r in rows)
"
python3 "$R" run --times 12 --label shuffled2 --base-seed 7 --seed-flag "--order-seed {seed}" -- python3 seeded.py > /dev/null 2>&1
t 0 "the same base seed gives the same seeds again" python3 -c "
import json,glob
a=[json.loads(l).get('seed') for l in open('$SEEDED')][1:]
b=[json.loads(l).get('seed') for l in open(glob.glob('.mstack/flaky/shuffled2-*.jsonl')[0])][1:]
assert a==b
"
t 1 "stop after the first failure" python3 "$R" run --times 12 --stop-after-fail 1 --label quick -- python3 -c "import sys; sys.exit(1)"
has "runs: 1 " "only one run was made"

echo "#### bisect"
T="python3 -m unittest {tests}"
t 0 "finds the polluter among four candidates" python3 "$R" bisect --template "$T" --victim tests.test_victim tests.test_a tests.test_b tests.test_c tests.test_d
has "polluter: tests.test_b" "names the right test"
printf 'tests.test_a\ntests.test_c\ntests.test_d\n' > clean.txt
t 2 "nothing to bisect when the victim passes after all candidates" python3 "$R" bisect --template "$T" --victim tests.test_victim --candidates clean.txt
t 2 "a victim that fails alone is not an order problem" python3 "$R" bisect --template "$T" --victim tests.test_counter_missing tests.test_a
t 2 "template without {tests}" python3 "$R" bisect --template "python3 -m unittest" --victim tests.test_victim tests.test_a
t 2 "no candidates" python3 "$R" bisect --template "$T" --victim tests.test_victim

echo "#### guard"
# copies of the original test are kept under .mstack/, which the scan leaves out
ORIG=.mstack/counter.orig
cp tests/test_counter.py "$ORIG"
python3 - <<'EOF'
import pathlib
p = pathlib.Path("tests/test_counter.py")
p.write_text(p.read_text().replace("    def test_every", "    @unittest.skip('unstable')\n    def test_every"))
EOF
t 1 "a skip marker is not a fix" python3 "$R" guard
has "BLOCK skip" "points at the line"
cp "$ORIG" tests/test_counter.py
python3 - <<'EOF'
import pathlib
p = pathlib.Path("tests/test_counter.py")
p.write_text(p.read_text().replace("        path = ", "        import time; time.sleep(2)\n        path = "))
EOF
t 0 "a fixed wait is a warning to read, not a block" python3 "$R" guard
has "warn  fixed wait" "the sleep is listed"
cp "$ORIG" tests/test_counter.py
printf '[pytest]\naddopts = --reruns 3\n' > pytest.ini
t 1 "a retry setting in a new, untracked file is found" python3 "$R" guard
has "pytest.ini:2" "file and line"
rm pytest.ini
python3 - <<'EOF'
import pathlib
pathlib.Path("tests/test_counter.py").write_text("import unittest\n")
EOF
t 1 "deleting the test is not a fix" python3 "$R" guard
has "removes 1 test definition" "counts removed tests"

echo "#### confirm (after a real fix: the test no longer depends on the counter)"
cat > tests/test_counter.py <<'EOF'
import unittest


class CounterTest(unittest.TestCase):
    def test_every_third_run_fails(self):
        n = 4
        self.assertNotEqual(n % 3, 0, "simulated intermittent failure")
EOF
t 0 "guard accepts the real fix" python3 "$R" guard
t 0 "after: 4 of 4 green" python3 "$R" run --times 4 --label after-short -- python3 -m unittest tests.test_counter
t 2 "4 green runs are too few against a 33% failure rate" python3 "$R" confirm --before "$BEFORE" --after "$(ls .mstack/flaky/after-short-*.jsonl)"
has "run at least 8" "says how many runs are needed"
t 0 "after: 12 of 12 green" python3 "$R" run --times 12 --label after -- python3 -m unittest tests.test_counter
AFTER=$(ls .mstack/flaky/after-2*.jsonl | head -1)
t 0 "confirm passes with enough runs and the same command" python3 "$R" confirm --before "$BEFORE" --after "$AFTER"
t 2 "a different command in the after record is not accepted" python3 "$R" confirm --before "$BEFORE" --after "$(ls .mstack/flaky/stable-*.jsonl)"
t 2 "a before record without a failure proves nothing" python3 "$R" confirm --before "$AFTER" --after "$AFTER"
t 1 "an after record with failures is a fail" python3 "$R" confirm --before "$BEFORE" --after "$BEFORE"
t 2 "missing record" python3 "$R" confirm --before nope.jsonl --after "$AFTER"
t 0 "summary lists the records" python3 "$R" summary
has "alone-" "includes the first record"
t 0 "nothing was overwritten: 9 run records exist, none from the refused calls" sh -c '[ "$(ls .mstack/flaky/*.jsonl | wc -l)" -eq 9 ]'

finish

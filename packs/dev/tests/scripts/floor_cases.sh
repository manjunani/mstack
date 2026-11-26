#!/bin/sh
# Script test for the review skill's floor guard: floor.py lists every place a diff makes a safety check
# weaker (tests deleted, removed, skipped or loosened, thresholds moved, checks silenced, CI steps removed),
# accepts a finding only with a real reason, blocks on a bad range or outside git, and writes nothing.
# Arguments: path to packs/dev, path of a NEW folder for the throwaway project (outside temporary folders).
DEV=$(cd "$1" && pwd); P="$2"; NAME=floor
. "$DEV/tests/scripts/lib.sh"
F="$DEV/skills/review/scripts/floor.py"
new_project "$P"

# edit <file> <old> <new>: replace the first occurrence; "\n" in old and new means a line break.
edit() {
  python3 -c 'import sys
p, o, n = (a.replace("\\n", "\n") for a in sys.argv[1:])
s = open(p).read()
if o not in s: sys.exit("edit: text not found in " + p)
open(p, "w").write(s.replace(o, n, 1))' "$@" || exit 9
}
# branch <name>: a fresh branch from the base commit, so every case starts from the same files.
branch() { $G checkout -q -B "$1" "$BASE" || exit 9; }
commit() { $G add -A . && $GC commit -qm "$1" || exit 9; }

mkdir -p src tests web scripts .github/workflows
printf 'def add(a, b):\n    return a + b\n' > src/calc.py
cat > tests/test_calc.py <<'EOF'
import unittest
from src.calc import add


class CalcTest(unittest.TestCase):
    def test_add(self):
        self.assertEqual(add(2, 2), 4)
        self.assertEqual(add(0, 0), 0)

    def test_negative(self):
        assert add(-1, -1) == -2
EOF
printf 'def test_old():\n    assert 1 + 1 == 2\n' > tests/test_old.py
printf 'import pytest\n\n\n@pytest.mark.skip(reason="needs the network")\ndef test_net():\n    assert True\n' > tests/test_slow.py
cat > web/app.test.js <<'EOF'
const { add } = require("./app");
it("adds", () => {
  expect(add(1, 2)).toStrictEqual(3);
});
it("adds zero", () => {
  expect(add(0, 0)).toBe(0);
});
EOF
printf 'exports.add = (a, b) => a + b;\n' > web/app.js
printf '[coverage:report]\nfail_under = 90\n\n[tool:pytest]\ntimeout = 10\n' > setup.cfg
printf 'git push origin main\n' > scripts/push.sh
cat > .github/workflows/ci.yml <<'EOF'
name: ci
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: lint
        run: ruff check .
      - name: test
        run: pytest
EOF
commit "base"
BASE=$($G rev-parse HEAD)

t 0 "help prints" python3 "$F" --help
has "check-disabled"

# a clean change: new code and a new test
branch clean
printf 'def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n' > src/calc.py
printf '\n    def test_sub(self):\n        self.assertEqual(add(3, -1), 2)\n' >> tests/test_calc.py
commit "add sub"
t 0 "a change that weakens nothing passes" python3 "$F" "$BASE..HEAD"
has "nothing weakened"
has "RESULT pass"
t 0 "a single ref means ref..HEAD" python3 "$F" "$BASE"
t 0 "an empty range passes" python3 "$F" "HEAD..HEAD"
has "checked: 0 changed files"

branch renamed
$G mv tests/test_slow.py tests/test_network.py
edit tests/test_calc.py "def test_negative(self):" "def test_negative_numbers(self):"
commit "rename"
t 0 "a renamed test file and a renamed test function are not removals" python3 "$F" "$BASE..HEAD"

# tests deleted or removed
branch deleted
$G rm -q tests/test_old.py
commit "drop old test"
t 1 "a deleted test file fails" python3 "$F" "$BASE..HEAD"
has "FLOOR test-deleted tests/test_old.py:1 (before) \"def test_old():\""
has "RESULT fail: 1 place weaken a safety floor"

branch removed
edit tests/test_calc.py "\n    def test_negative(self):\n        assert add(-1, -1) == -2\n" ""
commit "drop a test"
t 1 "a removed test function fails" python3 "$F" "$BASE..HEAD"
has "FLOOR test-removed tests/test_calc.py:10 (before) \"def test_negative(self):\" tests in this file: -1 +0"
has "FLOOR assert-removed tests/test_calc.py:11 (before)"

branch jsremoved
edit web/app.test.js "it(\"adds zero\", () => {\n  expect(add(0, 0)).toBe(0);\n});\n" ""
commit "drop a js case"
t 1 "a removed it() case fails" python3 "$F" "$BASE..HEAD"
has "FLOOR test-removed web/app.test.js:5 (before) \"it(\"adds zero\", () => {\""

# assertions removed or loosened
branch asserts
edit tests/test_calc.py "        self.assertEqual(add(0, 0), 0)\n" ""
commit "fewer asserts"
t 1 "a removed assertion fails" python3 "$F" "$BASE..HEAD"
has "FLOOR assert-removed tests/test_calc.py:8 (before) \"self.assertEqual(add(0, 0), 0)\" assertions in this file: -1 +0"

branch loosened
edit tests/test_calc.py "self.assertEqual(add(2, 2), 4)" "self.assertTrue(add(2, 2))"
edit tests/test_calc.py "assert add(-1, -1) == -2" "assert add(-1, -1)"
edit web/app.test.js "toStrictEqual(3)" "toEqual(3)"
commit "looser"
t 1 "loosened assertions fail" python3 "$F" "$BASE..HEAD"
has "FLOOR assert-loosened tests/test_calc.py:7 \"self.assertTrue(add(2, 2))\" weaker than the line it replaced: self.assertEqual(add(2, 2), 4)"
has "FLOOR assert-loosened tests/test_calc.py:11 \"assert add(-1, -1)\""
has "FLOOR assert-loosened web/app.test.js:3 \"expect(add(1, 2)).toEqual(3);\""
hasnt "assert-removed"

# thresholds and retries
branch weaker
edit setup.cfg "fail_under = 90" "fail_under = 70"
edit setup.cfg "timeout = 10" "timeout = 60"
commit "lower the bar"
t 1 "a lowered coverage minimum and a raised timeout fail" python3 "$F" "$BASE..HEAD"
has "FLOOR threshold-weakened setup.cfg:2 \"fail_under = 70\" lowered from fail_under = 90"
has "FLOOR threshold-weakened setup.cfg:5 \"timeout = 60\" raised from timeout = 10"

t 0 "--allow with a real reason accepts the findings in that file" python3 "$F" "$BASE..HEAD" --allow "setup.cfg:the old bar was set by mistake in the first commit"
has "accepted threshold-weakened setup.cfg:2"
has "2 findings accepted with a reason"
t 2 "--allow with a reason that is not words is blocked" python3 "$F" "$BASE..HEAD" --allow "setup.cfg:asdf"
has "is not real words"
t 2 "--allow with a filler reason is blocked" python3 "$F" "$BASE..HEAD" --allow "setup.cfg:ok ok ok ok ok ok ok"
t 2 "--allow with no reason is blocked" python3 "$F" "$BASE..HEAD" --allow "setup.cfg"
t 1 "--allow for another file accepts nothing here" python3 "$F" "$BASE..HEAD" --allow "web/*.js:the web tests are rewritten in the next change"
has "unused --allow: no finding in web/*.js"

branch stronger
edit setup.cfg "fail_under = 90" "fail_under = 95"
edit setup.cfg "timeout = 10" "timeout = 5"
commit "raise the bar"
t 0 "a higher minimum and a shorter timeout pass" python3 "$F" "$BASE..HEAD"

branch nocover
edit setup.cfg "fail_under = 90\n" ""
commit "no coverage minimum"
t 1 "a deleted coverage minimum fails" python3 "$F" "$BASE..HEAD"
has "FLOOR threshold-removed setup.cfg:2 (before) \"fail_under = 90\""

branch retry
edit tests/test_calc.py "    def test_add(self):" "    @pytest.mark.flaky(reruns=3)\n    def test_add(self):"
commit "retry"
t 1 "an added retry fails" python3 "$F" "$BASE..HEAD"
has "FLOOR retry-added tests/test_calc.py:6 \"@pytest.mark.flaky(reruns=3)\""

# skipped and focused tests
branch skipped
edit tests/test_calc.py "    def test_add(self):" "    @unittest.skip(\"later\")\n    def test_add(self):"
edit tests/test_old.py "def test_old():" "@pytest.mark.xfail\ndef test_old():"
edit web/app.test.js "it(\"adds\"" "it.only(\"adds\""
edit web/app.test.js "it(\"adds zero\"" "xit(\"adds zero\""
commit "skip"
t 1 "skip, xfail, only and xit markers fail" python3 "$F" "$BASE..HEAD"
has "FLOOR test-skipped tests/test_calc.py:6 \"@unittest.skip(\"later\")\""
has "FLOOR test-skipped tests/test_old.py:1 \"@pytest.mark.xfail\""
has "FLOOR test-skipped web/app.test.js:2 \"it.only(\"adds\", () => {\""
has "FLOOR test-skipped web/app.test.js:5 \"xit(\"adds zero\", () => {\""
hasnt "test-removed"

# checks turned off
branch silenced
edit .github/workflows/ci.yml "        run: pytest" "        run: pytest || true"
edit .github/workflows/ci.yml "        run: ruff check ." "        run: ruff check .\n        continue-on-error: true"
edit src/calc.py "def add(a, b):" "def add(a, b):  # type: ignore"
edit src/calc.py "    return a + b" "    return a + b  # noqa"
edit web/app.js "exports.add" "// @ts-ignore\n// eslint-disable-next-line\nexports.add"
edit scripts/push.sh "git push origin main" "git push --no-verify origin main"
commit "quiet"
t 1 "silenced checks fail" python3 "$F" "$BASE..HEAD"
has "FLOOR check-disabled .github/workflows/ci.yml:10 \"continue-on-error: true\""
has "FLOOR check-disabled .github/workflows/ci.yml:12 \"run: pytest || true\" a failing command now counts as success"
has "FLOOR check-disabled src/calc.py:1 \"def add(a, b):  # type: ignore\""
has "FLOOR check-disabled src/calc.py:2 \"return a + b  # noqa\""
has "FLOOR check-disabled web/app.js:1 \"// @ts-ignore\""
has "FLOOR check-disabled web/app.js:2 \"// eslint-disable-next-line\""
has "FLOOR check-disabled scripts/push.sh:1 \"git push --no-verify origin main\""
hasnt "ci-step-removed"

# CI steps and files removed
branch nolint
edit .github/workflows/ci.yml "      - name: lint\n        run: ruff check .\n" ""
commit "no lint step"
t 1 "a removed CI step fails" python3 "$F" "$BASE..HEAD"
has "FLOOR ci-step-removed .github/workflows/ci.yml:8 (before) \"- name: lint\""
has "FLOOR ci-step-removed .github/workflows/ci.yml:9 (before) \"run: ruff check .\""

branch noci
$G rm -q .github/workflows/ci.yml
commit "no ci"
t 1 "a deleted workflow file fails" python3 "$F" "$BASE..HEAD"
has "FLOOR ci-file-deleted .github/workflows/ci.yml:1 (before) \"name: ci\""

# bad input
t 2 "a range git does not know is blocked" python3 "$F" "no-such-branch..HEAD"
has "RESULT blocked: git does not know the range no-such-branch..HEAD"
t 2 "a single unknown ref is blocked" python3 "$F" "no-such-ref"

# uncommitted changes, untracked files, and nothing written
branch working
edit tests/test_calc.py "    def test_negative(self):" "    @pytest.mark.skip\n    def test_negative(self):"
printf 'it.skip("later", () => {});\n' > web/extra.test.js
snapshot() { (find . -path ./.git -prune -o -type f -print | sort | xargs cksum; cksum .git/index; $G status --porcelain -uall) 2>&1; }
BEFORE=$(snapshot)
t 1 "uncommitted and untracked changes are checked" python3 "$F"
has "range: uncommitted changes against HEAD"
has "FLOOR test-skipped tests/test_calc.py:10 \"@pytest.mark.skip\""
has "FLOOR test-skipped web/extra.test.js:1 \"it.skip(\"later\", () => {});\""
t 1 "a committed range in the same folder" python3 "$F" "$BASE..skipped"
t 2 "a bad --allow in the same folder" python3 "$F" --allow "x.py:no"
same "floor.py wrote nothing (files, index and git status unchanged)" "$(snapshot)" "$BEFORE"
same "no .mstack folder was made" "$([ -e .mstack ] && echo made || echo none)" "none"

mkdir "$P.nogit" && cd "$P.nogit" || exit 9
t 2 "outside a git repository is blocked" python3 "$F"
has "RESULT blocked: not inside a git repository"
finish

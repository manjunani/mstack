#!/bin/sh
# Exercise the test-gaps script in a throwaway project.
# Arguments: path to packs/test, path of a NEW folder to create the projects in (outside temporary folders).
PACK=$(cd "$1" && pwd); P="$2"
[ -e "$P" ] && { echo "refusing: $P already exists"; exit 9; }
. "$PACK/tests/scripts/lib.sh"
I="$PACK/skills/test-gaps/scripts/inventory.py"
git=/usr/bin/git
mkdir -p "$P/app/src/billing" "$P/app/src/auth" "$P/app/tests" "$P/app/web" "$P/app/.github/workflows" "$P/empty" "$P/covered/tests" "$P/nogit/lib"
P=$(cd "$P" && pwd)

echo "#### scan: a project with gaps"
cd "$P/app" || exit 9
printf 'def total(items):\n    return sum(items)\n' > src/cart.py
printf 'def number(n):\n    return f"INV-{n:05d}"\n' > src/billing/invoice.py
printf 'def vat(amount):\n    return round(amount * 0.2, 2)\n' > src/billing/tax.py
printf 'def start(user):\n    return {"user": user}\n\n\ndef end(session):\n    session.clear()\n' > src/auth/session.py
printf 'def issue(user):\n    return "t-" + user\n' > src/auth/tokens.py
printf 'from src.cart import total\nfrom src.billing import invoice\n\n\ndef test_total():\n    assert total([1, 2]) == 3\n\n\ndef test_number():\n    assert invoice.number(7) == "INV-00007"\n' > tests/test_cart.py
printf 'export const greet = (n) => "hi " + n;\n' > web/app.js
printf 'export const money = (n) => n.toFixed(2);\n' > web/format.js
printf 'import { greet } from "./app";\ntest("greets", () => expect(greet("a")).toBe("hi a"));\n' > web/app.test.js
printf '{"name": "app", "scripts": {"test": "jest"}, "devDependencies": {"jest": "^29.0.0"}}\n' > package.json
printf '[pytest]\ntestpaths = tests\n' > pytest.ini
printf 'name: ci\non: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: python3 -m pytest -q\n' > .github/workflows/ci.yml
printf '.mstack/\n' > .gitignore
$git init -q -b main && $git add -A && $git -c user.name=t -c user.email=t@t commit -qm first
for n in 1 2 3; do echo "# change $n" >> src/billing/tax.py; $git -c user.name=t -c user.email=t@t commit -qam "tax $n"; done

t 2 "scan lists gaps and ends as not verified" python3 "$I" scan
has "source files: 7   test files: 2" "counts source and test files"
has "names or imports them: 3" "cart by name, invoice by import, app.js by name and import"
has "pytest " "detects pytest from pytest.ini"
has "jest " "detects jest from package.json"
has ".github/workflows/ci.yml" "finds the CI config"
has "runs tests: .github/workflows/ci.yml:7" "finds the test command in CI"
has "      4      5  src/billing/tax.py" "the file changed most often is listed with its change count"
has "      2      8  src/auth/" "a folder with no touched file is listed"
t 0 "tax.py is the first row of the gap table" sh -c "grep -q '^| 1 |  | src/billing/tax.py | 4 |' .mstack/test-gaps/gaps.md"
t 0 "inventory.json holds the four untouched files; src/billing is not called bare because invoice.py is imported" python3 -c "
import json; d=json.load(open('.mstack/test-gaps/inventory.json'))
assert sorted(r['file'] for r in d['untouched'])==['src/auth/session.py','src/auth/tokens.py','src/billing/tax.py','web/format.js'], d['untouched']
assert d['top'][0]=='src/billing/tax.py' and len(d['top'])==4
assert [f['folder'] for f in d['bare_folders']]==['src/auth'], d['bare_folders']
"
t 2 "a second scan writes gaps-2.md and keeps the first" python3 "$I" scan
t 0 "both tables exist" sh -c "test -f .mstack/test-gaps/gaps.md && test -f .mstack/test-gaps/gaps-2.md"

echo "#### check"
t 1 "an unfilled table fails" python3 "$I" check
has "no risk" "risk is required"
has "action is ''" "action is required"
fill() { python3 - "$@" <<'EOF'
import pathlib, sys
rows = dict(a.split("=", 1) for a in sys.argv[1:])
p = pathlib.Path(".mstack/test-gaps/gaps.md")
out = []
for line in p.read_text().splitlines():
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    if len(cells) == 8 and cells[2] in rows:
        risk, action, test, reason = rows[cells[2]].split(";")
        cells[1], cells[5], cells[6], cells[7] = risk, action, test, reason
        line = "| " + " | ".join(cells) + " |"
    out.append(line)
p.write_text("\n".join(out) + "\n")
EOF
}
fill "src/billing/tax.py=customers are charged the wrong VAT;add;tests/test_tax.py::test_vat_rounds_half_up;" \
     "src/auth/session.py=a logged out user keeps access;update;tests/test_cart.py::test_missing_name;" \
     "src/auth/tokens.py=tokens can be guessed;no-test;;too small" \
     "web/format.js=prices show with the wrong decimals;sometime;;"
t 1 "bad rows fail" python3 "$I" check
has "'test_missing_name' is not in tests/test_cart.py" "update needs a test that exists"
has "'no-test' needs a reason of at least five words (found 2)" "a reason has to say something"
has "action is 'sometime'" "unknown action"
fill "src/auth/session.py=a logged out user keeps access;add;tests/test_session.py;" \
     "src/auth/tokens.py=tokens can be guessed;no-test;;replaced by the identity provider next sprint, file will be deleted" \
     "web/format.js=prices show with the wrong decimals;keep;web/app.test.js;"
t 2 "decided but not written yet is not verified" python3 "$I" check
has "tests/test_tax.py is named but not written yet" "names the missing test"
has "2 test(s) are decided but not written yet" "counts them"
printf 'from src.billing.tax import vat\n\n\ndef test_vat_rounds_half_up():\n    assert vat(10.03) == 2.01\n' > tests/test_tax.py
printf 'from src.auth import session\n\n\ndef test_end_clears():\n    s = session.start("a"); session.end(s); assert s == {}\n' > tests/test_session.py
t 0 "every top risk has a test that exists or a reason" python3 "$I" check
python3 - <<'EOF'
import pathlib
p = pathlib.Path(".mstack/test-gaps/gaps.md")
p.write_text("\n".join(l for l in p.read_text().splitlines() if "tokens.py" not in l) + "\n")
EOF
t 1 "removing a row is not a decision" python3 "$I" check
has "top risk src/auth/tokens.py from the inventory has no row" "the dropped risk is named"
t 2 "a missing gap file is not verified" python3 "$I" check --gaps nope.md
t 2 "after the tests were written, a new scan lists only what is left" python3 "$I" scan
has "names or imports them: 5" "the two new test files now touch tax.py and session.py"

echo "#### other projects"
cd "$P/empty" || exit 9
t 2 "an empty folder: nothing to inventory" python3 "$I" scan
t 2 "check without a scan" python3 "$I" check
cd "$P/covered" || exit 9
printf 'def add(a, b):\n    return a + b\n' > calc.py
printf 'import calc\n\n\ndef test_add():\n    assert calc.add(1, 2) == 3\n' > tests/test_calc.py
$git init -q -b main && $git add -A && $git -c user.name=t -c user.email=t@t commit -qm first
t 0 "a project with no gap passes with nothing to decide" python3 "$I" scan
has "none found: nothing runs the tests automatically" "says there is no CI config"
t 0 "check passes on the empty gap table" python3 "$I" check
cd "$P/nogit" || exit 9
printf 'def a():\n    return 1\n' > lib/a.py
GIT_CEILING_DIRECTORIES="$P" t 2 "outside git: files come from a folder walk, history is not verified" env GIT_CEILING_DIRECTORIES="$P" python3 "$I" scan
has "recent changes: not verified" "says the history part did not run"
has "folder walk" "says how files were listed"

finish

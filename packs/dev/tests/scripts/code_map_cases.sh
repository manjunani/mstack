#!/bin/sh
# Script test for the code-map skill: code_map.py finds definitions and uses (Python exact, JavaScript by text),
# skips comments, strings and vendored folders, suggests close names, traces the impact of a range with its
# tests, fails when a removed name is still used, caps the map, and blocks outside a git repository.
# Arguments: path to packs/dev, path of a NEW folder for the throwaway project (outside temporary folders).
DEV=$(cd "$1" && pwd); P="$(cd "$(dirname "$2")" && pwd)/$(basename "$2")"; NAME=code-map
. "$DEV/tests/scripts/lib.sh"
C="$DEV/skills/code-map/scripts/code_map.py"
new_project "$P"
mkdir -p src/billing tests web node_modules/lib .venv/lib svc
touch src/billing/__init__.py .venv/pyvenv.cfg
cat > src/billing/tax.py <<'EOF'
RATE = 0.2

def compute_tax(amount):
    return round(amount * RATE, 2)

def compute_tax_total(items):
    return sum(compute_tax(i) for i in items)

class Invoice:
    def total(self):
        return compute_tax(10)
EOF
cat > src/app.py <<'EOF'
from billing.tax import compute_tax
from billing import tax

def checkout(amount):
    # compute_tax is called here
    return amount + compute_tax(amount)

def report():
    print("compute_tax")
    return tax.compute_tax_total([1, 2])

handler = compute_tax
EOF
cat > src/api.py <<'EOF'
from app import checkout

def create_order(x):
    return checkout(x)
EOF
printf 'import pricing\n\ndef summary():\n    return pricing.compute_tax(1)\n' > src/report.py
cat > tests/test_tax.py <<'EOF'
from billing.tax import compute_tax

def test_compute_tax():
    assert compute_tax(10) == 2.0
EOF
cat > tests/test_api.py <<'EOF'
from api import create_order

def test_create():
    assert create_order(10) == 12.0
EOF
cat > web/price.js <<'EOF'
// formatPrice is documented here
import { formatPrice } from './format.js';
const { parse } = require('./parse');

export function showPrice(el, value) {
  el.textContent = formatPrice(parse(value));
  console.log("formatPrice called");
}
EOF
cat > web/format.js <<'EOF'
export function formatPrice(v) {
  return '$' + v.toFixed(2);
}
export const formatPriceShort = (v) => '$' + Math.round(v);
EOF
echo 'export function parse(s: string): number { return Number(s); }' > web/parse.ts
cat > svc/tax.go <<'EOF'
package svc

func ComputeTax(x float64) float64 { return x * 0.2 }

func Total(x float64) float64 {
	return x + ComputeTax(x) // ComputeTax again in a comment
}
EOF
echo 'function formatPrice() {}' > node_modules/lib/index.js
echo 'def compute_tax(): pass' > .venv/lib/vendored.py
$G add -A && $GC commit -qm "billing, app, web" && $G branch -q start

t 0 "help prints" python3 "$C" --help
t 0 "callers of a Python function" python3 "$C" callers compute_tax
has "src/billing/tax.py:3  def compute_tax  [exact]"
has "src/app.py:1  import  [exact]"
has "src/app.py:6  call in checkout  [exact]"
has "src/app.py:12  reference  [exact]"
has "src/billing/tax.py:11  call in Invoice.total  [exact]"
has "tests that reference it (1): tests/test_tax.py"
hasnt "src/app.py:5"
hasnt "src/app.py:9"
hasnt "src/app.py:10"
hasnt "node_modules"
hasnt ".venv"
has "src/report.py:4  method call  [exact]"
has "RESULT pass: 1 definition, 7 uses in 3 files (exact: 8, text match: 0); 1 same-name uses set apart"

t 1 "a near-miss name is not found, close names are offered" python3 "$C" callers compute_taxes
has "similar names that do exist: compute_tax"
has "RESULT fail: no definition or use of 'compute_taxes'"
t 1 "a missing name fails with a clear line" python3 "$C" callers no_such_thing_here
has "RESULT fail: no definition or use of 'no_such_thing_here' found in"
t 2 "a string that is no name is not verified" python3 "$C" callers "foo bar"

t 0 "callers of a JavaScript function are text matches" python3 "$C" callers formatPrice
has "web/format.js:1  def formatPrice  [text match]"
has "web/price.js:2  import  [text match]"
has "web/price.js:6  call in showPrice  [text match]"
hasnt "web/price.js:1 "
hasnt "web/price.js:7"
hasnt "web/format.js:4"
hasnt "node_modules"
t 0 "callers of a Go function skip the comment" python3 "$C" callers ComputeTax
has "svc/tax.go:3  def ComputeTax  [text match]"
has "svc/tax.go:6  call in Total  [text match]"
t 0 "a qualified method name" python3 "$C" callers Invoice.total
has "def Invoice.total  [exact]"
t 0 "a file path lists who imports that module" python3 "$C" callers src/billing/tax.py
has "src/app.py:2  import"
has "tests/test_tax.py:1  import"
hasnt "call in checkout"

t 0 "map outlines modules, definitions and import edges" python3 "$C" map
has "src/billing/tax.py: compute_tax, compute_tax_total, class Invoice(1 methods)"
has "src/app.py: checkout, report"
has "    -> src/billing/tax.py"
has "web/price.js: showPrice  [text match]"
hasnt "node_modules"
mkdir -p many
i=1; while [ $i -le 60 ]; do printf 'def f%s():\n    return %s\n' $i $i > many/m$i.py; i=$((i + 1)); done
t 0 "map output stays under its cap" python3 "$C" map --max-lines 15
has "more files not shown (cap 15 lines)"
same "map prints at most cap + 1 lines" "$(printf '%s\n' "$OUT" | awk 'END { print (NR <= 16) }')" "1"
echo "many/" >> .git/info/exclude
t 2 "map of a folder that is not there" python3 "$C" map no/such/folder

# impact of a committed range: compute_tax changes on a branch
$G checkout -q -b feature
sed -i.bak 's/round(amount \* RATE, 2)/round(amount * RATE, 3)/' src/billing/tax.py && rm src/billing/tax.py.bak
$G add -A && $GC commit -qm "more precise tax"
t 0 "impact of a range finds the change, callers two levels out and the tests" python3 "$C" impact start..feature
has "src/billing/tax.py:3  changed  def compute_tax  [exact]"
has "compute_tax <- src/app.py:6  call in checkout"
has "checkout <- src/api.py:4  call in create_order"
has "tests/test_tax.py  (compute_tax)"
has "  1. src/billing/tax.py  (changed"
has "RESULT pass: 1 changed definition"
has "compute_tax_total <- src/app.py:10  method call in report"
t 0 "three-dot range from the merge base" python3 "$C" impact main...feature
has "changed  def compute_tax"
t 2 "a bad range is not verified" python3 "$C" impact nope..feature
has "bad range"
t 2 "a word that is no commit and no file" python3 "$C" impact no-such-ref
t 0 "impact of named files counts every definition in them" python3 "$C" impact src/api.py
has "changed  def create_order"
has "tests/test_api.py  (create_order)"

# a rename in the working folder that leaves an old caller behind
sed -i.bak 's/def compute_tax_total/def sum_tax/' src/billing/tax.py && rm src/billing/tax.py.bak
t 1 "a removed name that is still called fails" python3 "$C" impact
has "removed  def compute_tax_total"
has "BROKEN compute_tax_total was removed and is defined nowhere now, but is still used at src/app.py:10"
has "RESULT fail: removed compute_tax_total is still used in 1 place"
sed -i.bak 's/tax.compute_tax_total/tax.sum_tax/' src/app.py && rm src/app.py.bak
t 0 "with the caller updated the rename passes" python3 "$C" impact
has "sum_tax <- src/app.py:10"
$G checkout -q -- .
t 0 "a clean working folder has nothing to trace" python3 "$C" impact
has "RESULT pass: nothing changed"

mkdir "$P.nogit" && cd "$P.nogit" || exit 9
printf 'def solo():\n    return 1\n\nsolo()\n' > one.py
t 2 "impact outside a git repository is blocked" python3 "$C" impact
has "not inside a git repository"
t 0 "callers works without git" python3 "$C" callers solo
has "one.py:4  call  [exact]"
finish

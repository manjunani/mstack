#!/bin/sh
# Exercise the test-cases scripts in a throwaway folder.
# Arguments: path to packs/test, path of a NEW folder to create (outside temporary folders).
PACK=$(cd "$1" && pwd); P="$2"
[ -e "$P" ] && { echo "refusing: $P already exists"; exit 9; }
. "$PACK/tests/scripts/lib.sh"
W="$PACK/skills/test-cases/scripts/pairwise.py"
C="$PACK/skills/test-cases/scripts/cases.py"
mkdir -p "$P" && cd "$P" || exit 9

# An independent pair counter: it shares no code with pairwise.py.
cat > recount.py <<'EOF'
import itertools, json, sys
rows = json.load(open(sys.argv[1]))
params = json.loads(sys.argv[2])
excluded = json.loads(sys.argv[3]) if len(sys.argv) > 3 else []
want_missing = json.loads(sys.argv[4]) if len(sys.argv) > 4 else []
names = list(params)
seen = {(a, r[a], b, r[b]) for r in rows for a, b in itertools.combinations(names, 2)}
allp = {(a, x, b, y) for a, b in itertools.combinations(names, 2) for x in params[a] for y in params[b]}
missing = sorted(allp - seen)
bad = [r for r in rows for e in excluded if all(r[k] == v for k, v in e.items())]
print(f"rows {len(rows)} pairs {len(allp)} missing {len(missing)} rows-with-excluded {len(bad)}")
sys.exit(0 if not bad and [list(m) for m in missing] == want_missing else 1)
EOF

echo "#### pairwise.py"
t 2 "one parameter is not enough" python3 "$W" --param "a=1,2"
t 2 "malformed --param" python3 "$W" --param "a" --param "b=1,2"
t 2 "a value listed twice" python3 "$W" --param "a=1,1" --param "b=1,2"
t 2 "exclusion with an unknown value" python3 "$W" --param "a=1,2" --param "b=1,2" --exclude "a=9,b=1"
t 2 "exclusion with one parameter only" python3 "$W" --param "a=1,2" --param "b=1,2" --exclude "a=1"
t 0 "3 x 3 x 2: table on screen" python3 "$W" --param "browser=chrome,firefox,safari" --param "os=mac,windows,linux" --param "role=admin,member" --covers R-003
has "| id | covers | browser | os | role | expected |" "Markdown header with an empty expected column"
has "all combinations would be: 18" "states the full product"
has "pairs covered: 21 of 21" "pair count is printed"
P3='{"browser":["chrome","firefox","safari"],"os":["mac","windows","linux"],"role":["admin","member"]}'
t 0 "3 x 3 x 2 as JSON to a new file" python3 "$W" --param "browser=chrome,firefox,safari" --param "os=mac,windows,linux" --param "role=admin,member" --format json --out p3.json
t 2 "refuses to overwrite the output file" python3 "$W" --param "a=1,2" --param "b=1,2" --format json --out p3.json
python3 - <<'EOF'
import json; rows = json.load(open("p3.json")); assert rows[0]["expected"] == "" and rows[0]["id"] == "TC-001", rows[0]
json.dump([{k: v for k, v in r.items() if k not in ("id", "covers", "expected")} for r in rows], open("p3.rows.json", "w"))
EOF
t 0 "independent recount: every pair is in some row" python3 recount.py p3.rows.json "$P3"
t 0 "fewer rows than all combinations (at most 12 of 18)" python3 -c "import json,sys; n=len(json.load(open('p3.json'))); print(n); sys.exit(0 if 9 <= n <= 12 else 1)"
t 0 "same input gives the same rows again" sh -c "python3 '$W' --param 'browser=chrome,firefox,safari' --param 'os=mac,windows,linux' --param 'role=admin,member' --format json --out p3b.json >/dev/null && cmp p3.json p3b.json"

cat > model.json <<'EOF'
{"parameters": {"plan": ["free", "pro", "team", "enterprise"], "billing": ["monthly", "yearly", "invoice", "none"],
                "region": ["eu", "us", "in", "jp"], "sso": ["on", "off", "forced", "legacy"],
                "seats": ["1", "5", "50", "500"], "trial": ["yes", "no", "expired", "extended"]},
 "exclude": [{"plan": "free", "billing": "invoice"}, {"plan": "free", "sso": "forced"}]}
EOF
t 0 "6 parameters x 4 values with two exclusions" python3 "$W" --model model.json --format json --out big.json
has "all combinations would be: 4096" "full product"
has "impossible under the exclusions: plan=free with billing=invoice" "names the impossible pair"
python3 - <<'EOF'
import json
json.dump([{k: v for k, v in r.items() if k not in ("id", "covers", "expected")} for r in json.load(open("big.json"))], open("big.rows.json", "w"))
EOF
t 0 "independent recount: only the two excluded pairs are missing, no row breaks an exclusion" python3 recount.py big.rows.json "$(python3 -c "import json;print(json.dumps(json.load(open('model.json'))['parameters']))")" '[{"plan":"free","billing":"invoice"},{"plan":"free","sso":"forced"}]' '[["plan","free","billing","invoice"],["plan","free","sso","forced"]]'
t 0 "about 16 to 40 rows stand in for 4096" python3 -c "import json,sys; n=len(json.load(open('big.json'))); print(n); sys.exit(0 if 16 <= n <= 40 else 1)"
t 0 "an exclusion can make a pair impossible indirectly" python3 "$W" --param "a=1,2" --param "b=1,2" --param "c=1" --exclude "a=1,c=1"
has "impossible under the exclusions: a=1 with b=1" "found by trying to complete the row"
t 1 "exclusions that leave no valid row" python3 "$W" --param "a=1" --param "b=1" --exclude "a=1,b=1"
t 0 "csv output" python3 "$W" --param "a=1,2" --param "b=x,y" --format csv
has "id,covers,a,b,expected" "csv header"

echo "#### cases.py"
cat > spec.md <<'EOF'
# Discount codes

## Done when

- R-001: A code of 4 to 12 letters or digits is accepted.
- **R-002** A code that expired yesterday is refused with the message "This code has expired".
- [ ] R-003 The discount is never larger than the cart total.
| R-004 | The same code cannot be used twice by one account |

Notes: see R-001 for the format. This line does not start with an id.
EOF
t 0 "ids lists four requirement lines" python3 "$C" ids --spec spec.md
has "4 requirement line(s)" "list item, bold, checkbox and table row forms"
printf '# Notes\nNothing numbered here.\n' > plain.md
t 2 "a spec without ids is not verified" python3 "$C" ids --spec plain.md
t 2 "missing spec file" python3 "$C" check --spec nope.md --cases nope.md
printf 'Just prose, no table.\n' > notable.md
t 2 "a cases file without a table is not verified" python3 "$C" check --spec spec.md --cases notable.md

cat > bad.md <<'EOF'
| id | covers | code | expected |
|---|---|---|---|
| TC-001 | R-001 | ABCD | accepted |
| TC-002 | R-001 | ABC | 400 or 422 |
| TC-003 | R-002 | OLD1 | works as expected |
| TC-004 | R-002 | OLD2 | |
| TC-004 | R-003 | BIG1 | TBD |
| TC-006 | R-009 | X | refused with "Unknown code" |
| TC-007 |  | Y | refused with "Unknown code" |
| TC-008 | R-003 | ABCD | refused with "Too short" |
| TC-009 | R-003 | BIG2 | error |
EOF
t 1 "a table with faults fails" python3 "$C" check --spec spec.md --cases bad.md
has "TC-002 (line 4): expected allows more than one result" "two results at once"
has "TC-003 (line 5): expected is not observable" "vague phrase"
has "TC-004 (line 6): no expected result" "empty expected"
has "id already used on line 6" "repeated case id"
has "expected is a placeholder" "placeholder"
has "covers R-009, which is not a requirement line" "unknown requirement"
has "TC-007 (line 9): covers names no requirement id" "empty covers"
has "same inputs as case TC-001 but a different expected result" "conflicting cases"
has "expected is only 'error'" "bare word"
has "R-004 (spec line 8) has no case" "requirement without a case"

cat > good.md <<'EOF'
## Boundaries

| id | covers | code | expected |
|---|---|---|---|
| TC-001 | R-001 | ABCD (4 characters) | accepted; cart shows the discount line |
| TC-002 | R-001 | ABC (3 characters) | refused with "Code must be 4 to 12 characters" |
| TC-003 | R-001 | 13 characters | refused with "Code must be 4 to 12 characters" |
| TC-004 | R-002 | expired yesterday | refused with "This code has expired" |
| TC-005 | R-002 | expires today | accepted |

## State

| Case | Requirement | cart total | discount | Expected result |
|---|---|---|---|---|
| TC-006 | R-003 | 10.00 | 15.00 | discount applied is 10.00; total is 0.00 |
| TC-007 | R-004, R-001 | 20.00 | 5.00, second use | refused with "You have already used this code or it is not valid for you" |
EOF
t 0 "a complete table passes" python3 "$C" check --spec spec.md --cases good.md
has "7 cases in 2 table(s)" "both tables are read, with different column names"
lacks "problem:" "quoted text with 'or' inside is not taken as two results"
printf '| id | covers | expected |\n|---|---|---|\n' > empty.md
t 1 "a header with no rows fails" python3 "$C" check --spec spec.md --cases empty.md

echo "#### the two scripts together"
python3 "$W" --param "length=3,4,12,13" --param "state=active,expired" --covers R-001 --out gen.md > /dev/null
t 1 "generated rows fail the check until expected is filled" python3 "$C" check --spec spec.md --cases gen.md
has "no expected result" "the empty column is caught"

finish

#!/bin/sh
# Exercise the test-data scripts in a throwaway project.
# Arguments: path to packs/test, path of a NEW folder to create the project in (outside temporary folders).
PACK=$(cd "$1" && pwd); P="$2"
[ -e "$P" ] && { echo "refusing: $P already exists"; exit 9; }
. "$PACK/tests/scripts/lib.sh"
S="$PACK/skills/test-data/scripts/pii_scan.py"
C="$PACK/skills/test-data/scripts/repeat_check.py"
mkdir -p "$P/tests/fixtures" "$P/db/seeds" "$P/src" "$P/clean/fixtures" "$P/none/src" && cd "$P" || exit 9

# The risky values are put together here at run time, so that this test file itself holds no
# value that looks like a real person's data.
python3 - "$PACK" <<'EOF'
import json, pathlib, sys
sys.path.insert(0, sys.argv[1] + "/skills/test-data/scripts")
import pii_scan

def with_luhn(body):
    return next(body + str(d) for d in range(10) if pii_scan.luhn(body + str(d)))

def with_verhoeff(body):
    return next(body + str(d) for d in range(10) if pii_scan.verhoeff(body + str(d)))

mail = "@" + "gm" + "ail.com"
card = with_luhn("453914880343646")
aadhaar = with_verhoeff("49372815064")
ssn = "-".join(["412", "67", "3581"])
users = [
    {"name": "A", "email": "ravi.kumar" + mail, "note": "line 2: public mail provider"},
    {"name": "B", "email": "anna@example.com", "note": "reserved domain"},
    {"name": "C", "email": "dev@acme-corp.io", "note": "line 4: company domain, warning"},
    {"name": "D", "email": "bob@shop.test", "note": "reserved top-level name"},
    {"name": "E", "contact": "+" + "91 98450 " + "31276", "note": "line 6: international number"},
    {"name": "F", "contact": "+1 (415) 555-0132", "note": "fictional 555-01xx"},
    {"name": "G", "contact": "(" + "212) 867-" + "5309", "note": "line 8: North American number"},
    {"name": "H", "phone": "07700 900123", "note": "drama range"},
    {"name": "I", "phone": "0000000000", "note": "made up"},
    {"name": "J", "mobile": "98" + "4503" + "1276", "note": "line 11: bare digits on a line that says mobile"},
    {"name": "K", "card": "4242 4242 4242 4242", "note": "published test card"},
    {"name": "L", "card": " ".join(card[i:i + 4] for i in range(0, 16, 4)), "note": "line 13: passes the Luhn check"},
    {"name": "M", "card": card + " 12/29", "exp": "", "note": "line 14: the same card with an expiry after it"},
    {"name": "N", "order_id": "1731234567890", "note": "13 digit timestamp, not a card"},
    {"name": "O", "ssn": "078-05-1120", "note": "advertising number"},
    {"name": "P", "ssn": "000-12-3456", "note": "area never issued"},
    {"name": "Q", "ssn": ssn, "note": "line 18: could have been issued"},
    {"name": "R", "uid": " ".join(aadhaar[i:i + 4] for i in range(0, 12, 4)), "note": "line 19: passes the Verhoeff check"},
    {"name": "S", "uid": "1234 5678 9012", "note": "fails the check"},
    {"name": "T", "pan": "ABC" + "PK" + "1234" + "L", "note": "line 21: PAN shape"},
    {"name": "U", "ni": "QQ" + " 12 34 56 " + "C", "note": "QQ is not a valid prefix"},
    {"name": "V", "ni": "AB" + " 12 34 56 " + "C", "note": "line 23: NINO shape"},
    {"name": "W", "version": "lodash@4.17.21", "id": "550e8400-e29b-41d4-a716-446655440000", "note": "not an email, not a phone"},
]
lines = ["["] + ["  " + json.dumps(u) + ("," if i < len(users) - 1 else "") for i, u in enumerate(users)] + ["]"]
pathlib.Path("tests/fixtures/users.json").write_text("\n".join(lines) + "\n")
pathlib.Path("db/seeds/seed_users.sql").write_text("INSERT INTO users (email) VALUES ('ops@example.org'), ('mia" + mail + "');\n")
pathlib.Path("src/app.py").write_text("ADMIN = 'owner" + mail + "'  # not test data, so not scanned by default\n")
pathlib.Path("tests/fixtures/logo.bin").write_bytes(b"\x00\x01\x02" * 50)
pathlib.Path("clean/fixtures/users.json").write_text(json.dumps([{"email": "a@example.com", "phone": "+1 202 555 0147", "card": "5555 5555 5555 4444"}]) + "\n")
pathlib.Path("none/src/app.py").write_text("x = 1\n")
# known Verhoeff examples: the tables in the script are right if these hold
assert pii_scan.verhoeff("2363") and pii_scan.verhoeff("123451") and pii_scan.verhoeff("1428570") and not pii_scan.verhoeff("2364")
assert pii_scan.luhn("79927398713") and not pii_scan.luhn("79927398710")
EOF
[ $? = 0 ] || { echo "could not build the fixtures"; exit 9; }

echo "#### pii_scan.py"
t 1 "finds the risky values in fixtures and seeds" python3 "$S"
has "scanned 3 text file(s), passed over 1 binary file(s)" "two fixture files and one seed file; src/ is not test data; the binary file is left out"
has "findings: 11 (aadhaar 1, card 2, email 2, nino 1, pan 1, phone 3, ssn 1)" "count per kind"
has "tests/fixtures/users.json:2: r***@gmail.com" "email at a public provider, masked"
has "db/seeds/seed_users.sql:1: m***@gmail.com" "the seed file is scanned too"
has "warn  email-domain  tests/fixtures/users.json:4" "a company domain is a warning"
has "phone         tests/fixtures/users.json:6:" "international number"
has "phone         tests/fixtures/users.json:8:" "North American number"
has "phone         tests/fixtures/users.json:11:" "bare digits next to the word mobile"
has "card          tests/fixtures/users.json:13:" "Luhn-valid card"
has "card          tests/fixtures/users.json:14:" "card followed by an expiry date"
has "ssn           tests/fixtures/users.json:18:" "issuable SSN"
has "aadhaar       tests/fixtures/users.json:19:" "Verhoeff-valid number"
has "pan           tests/fixtures/users.json:21:" "PAN shape"
has "nino          tests/fixtures/users.json:23:" "NINO shape"
for line in 3 5 7 9 10 12 15 16 17 20 22 24; do lacks "users.json:$line:" "line $line holds a safe value and is not reported"; done
lacks "0343" "the card number is not printed in full"
has "marked unverified" "says that the reference lists are unverified"
t 1 "strict: the company-domain email counts as a finding" python3 "$S" --strict
has "findings: 12" "one more finding"
t 1 "an explicit path outside the test data folders is scanned when named" python3 "$S" src
has "src/app.py:1: o***@gmail.com" "found in the named source file"
t 0 "a clean fixture folder passes" python3 "$S" clean
t 2 "a project with no test data files is not verified, not a pass" python3 "$S" --root none
t 2 "a path that does not exist is not verified" python3 "$S" nope
mkdir -p .mstack/test-data
python3 - <<'EOF'
import json, pathlib
row = next(r for r in json.loads(pathlib.Path("tests/fixtures/users.json").read_text()) if r["name"] == "T")
pathlib.Path(".mstack/test-data/allow.txt").write_text("# confirmed as invented by the owner\n" + row["pan"] + "\n")
EOF
t 1 "an allowed value is counted, not hidden" python3 "$S"
has "findings: 10" "one finding fewer"
has "allowed by allow.txt: 1" "the allowed value is counted"

echo "#### repeat_check.py"
cat > factory_fixed.py <<'EOF'
import random
rng = random.Random(7)
for i in range(5):
    print(f"user{i},user{i}@example.com,{rng.randint(18, 90)}")
EOF
cat > factory_loose.py <<'EOF'
import uuid
for i in range(5):
    print(f"user{i},{uuid.uuid4()}")
EOF
cat > stamped.py <<'EOF'
import time
print(f"generated at {time.time_ns()}")
print("user0,user0@example.com")
EOF
cat > seed.py <<'EOF'
import sqlite3, sys
mode, db = sys.argv[1], sys.argv[2]
con = sqlite3.connect(db)
if mode == "append":
    con.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT)")
    con.executemany("INSERT INTO users (email) VALUES (?)", [("a@example.com",), ("b@example.com",)])
elif mode == "upsert":
    con.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT)")
    con.executemany("INSERT OR IGNORE INTO users (id, email) VALUES (?, ?)", [(1, "a@example.com"), (2, "b@example.com")])
else:
    con.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT UNIQUE)")
    con.executemany("INSERT INTO users (id, email) VALUES (?, ?)", [(1, "a@example.com")])
con.commit()
EOF
cat > dump.py <<'EOF'
import sqlite3, sys
for row in sqlite3.connect(sys.argv[1]).execute("SELECT id, email FROM users ORDER BY id"):
    print(row)
EOF
cat > writer.py <<'EOF'
import json, pathlib
pathlib.Path("out.json").write_text(json.dumps({"users": [1, 2, 3]}))
EOF
t 2 "no command" python3 "$C"
t 2 "one run is refused" python3 "$C" --runs 1 -- python3 factory_fixed.py
t 2 "program not found" python3 "$C" -- no-such-seed-tool
t 2 "the command fails on the first run" python3 "$C" -- python3 -c "import sys; sys.exit(4)"
t 2 "empty output is nothing to compare" python3 "$C" -- python3 -c "pass"
t 2 "--no-stdout with nothing else" python3 "$C" --no-stdout -- python3 factory_fixed.py
t 0 "a factory with a fixed seed gives the same rows twice" python3 "$C" --label fixed -- python3 factory_fixed.py
has "2 runs gave the same result (output)" "says what was compared"
t 1 "a factory with random ids differs" python3 "$C" --label loose -- python3 factory_loose.py
has "5 changed line(s)" "counts the differing lines"
t 1 "a timestamp line makes two runs differ" python3 "$C" --label stamped -- python3 stamped.py
t 0 "the same with the timestamp line ignored, and the report says so" python3 "$C" --label stamped --ignore "^generated at " -- python3 stamped.py
has "1 line(s) per run were left out by --ignore" "ignored lines are counted"
t 2 "ignoring every line leaves nothing to compare" python3 "$C" --ignore "." -- python3 stamped.py
t 1 "a seed that appends rows is not safe to run twice" python3 "$C" --label append --no-stdout --state "python3 dump.py append.db" -- python3 seed.py append append.db
has "+(3, 'a@example.com')" "shows the rows the second run added"
t 0 "a seed that upserts leaves the same state" python3 "$C" --label upsert --no-stdout --state "python3 dump.py upsert.db" -- python3 seed.py upsert upsert.db
t 1 "a seed that crashes on the second run is a fail" python3 "$C" --no-stdout --state "python3 dump.py crash.db" -- python3 seed.py strict crash.db
has "passed on run 1 and failed on run 2" "says which run failed"
t 2 "a state command that fails is not verified" python3 "$C" --no-stdout --state "python3 dump.py missing-table.db" -- python3 -c "print(1)"
t 0 "a written file is compared" python3 "$C" --no-stdout --file out.json -- python3 writer.py
t 2 "a file that is never written is not verified" python3 "$C" --no-stdout --file nope.json -- python3 writer.py
t 0 "three runs" python3 "$C" --runs 3 -- python3 factory_fixed.py
t 0 "both runs were saved for reading" sh -c "ls .mstack/test-data/repeat/loose-*-run1.txt .mstack/test-data/repeat/loose-*-run2.txt"

finish

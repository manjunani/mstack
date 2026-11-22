#!/bin/sh
# Check the duplicate, secret and search rules of remember's script. Arguments: record.py path, a NEW folder.
R="$1"; P="$2"
[ -e "$P" ] && { echo "refusing: $P already exists"; exit 9; }
mkdir -p "$P" && cd "$P" || exit 9
bad=0
expect() { want="$1"; shift; "$@" > out.txt 2>&1; got=$?; if [ "$got" = "$want" ]; then echo "ok   exit $got | $LABEL"; else echo "BAD  exit $got (want $want) | $LABEL"; tail -2 out.txt; bad=$((bad+1)); fi; }
LABEL="first decision is saved"
expect 0 python3 "$R" add --text "Store all timestamps in UTC in the database." --why "The team works in three time zones and local times caused two bugs."
LABEL="same decision in other words is refused"
expect 1 python3 "$R" add --text "All timestamps are stored in UTC in the database." --why "Three time zones caused bugs with local times."
LABEL="a different decision is saved"
expect 0 python3 "$R" add --text "Deploy to production only from the main branch." --why "A deploy from a feature branch shipped unreviewed code last month."
LABEL="password written as 'password is ...' is refused"
expect 1 python3 "$R" add --text "The deploy password is hunter2-prod-9921 for staging." --why "So that nobody has to ask for it again."
LABEL="password written as 'password: ...' is refused"
expect 1 python3 "$R" add --text "Staging login uses password: Tr0ub4dor-x9 for the admin user." --why "So that nobody has to ask for it again."
LABEL="a sentence that only mentions the word token is saved"
expect 0 python3 "$R" add --text "The session token is checked on every request by the gateway." --why "Services behind the gateway must not repeat the check and drift apart."
LABEL="too short is blocked"
expect 2 python3 "$R" add --text "Too short" --why "x"
LABEL="superseding an unknown id is blocked"
expect 2 python3 "$R" add --text "Keep the user's zone name in a second column beside UTC." --why "Reports need the local day, which UTC alone cannot give." --supersedes D-nope
LABEL="lint passes"
expect 0 python3 "$R" check
python3 "$R" find timestamps utc > out.txt; LABEL="search finds the UTC record"; if grep -q "UTC" out.txt; then echo "ok   | $LABEL"; else echo "BAD  | $LABEL"; bad=$((bad+1)); fi
python3 "$R" find kubernetes ingress > out.txt; LABEL="search reports no match for an unrelated subject"; if grep -q "no similar record" out.txt; then echo "ok   | $LABEL"; else echo "BAD  | $LABEL"; cat out.txt; bad=$((bad+1)); fi
echo "records saved: $(python3 "$R" list | wc -l | tr -d ' ') (want 3)"
echo "remember cases: 11 run, $bad wrong"
[ "$bad" = 0 ]

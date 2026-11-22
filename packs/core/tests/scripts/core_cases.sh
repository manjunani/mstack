#!/bin/sh
# Exercise the scripts of the mstack-core skills in a throwaway project.
# Arguments: path to packs/core, path of a NEW folder to create the project in (outside temporary folders).
CORE="$1"; P="$2"
[ -e "$P" ] && { echo "refusing: $P already exists"; exit 9; }
mkdir -p "$P/src" "$P/docs" && cd "$P" || exit 9
git=/usr/bin/git
$git init -q && echo "print('a')" > src/app.py && echo "# docs" > docs/guide.md
$git add -A && $git -c user.name=t -c user.email=t@t commit -qm "first"

echo "#### scope-lock"
L="$CORE/skills/scope-lock/scripts/lock.py"
python3 "$L" status; echo "exit $? (expect 2: no lock)"
python3 "$L" set /etc; echo "exit $? (expect 2: outside project)"
python3 "$L" set src --reason "parser work"; echo "exit $?"
python3 "$L" test docs/guide.md; echo "exit $? (expect 1)"
python3 "$L" test src/new.py; echo "exit $? (expect 0)"
python3 "$L" test .mstack/x.json; echo "exit $? (expect 0)"
G="$CORE/hooks/guard.py"
for f in docs/guide.md src/app.py; do
  printf '{"tool_name":"Edit","tool_input":{"file_path":"%s/%s"},"cwd":"%s"}' "$P" "$f" "$P" | python3 "$G" | grep -o '"permissionDecision": "[a-z]*"' || echo "guard: allow ($f)"
done
python3 "$L" release; echo "exit $?"
printf '{"tool_name":"Edit","tool_input":{"file_path":"%s/docs/guide.md"},"cwd":"%s"}' "$P" "$P" | python3 "$G" | grep -o '"permissionDecision": "[a-z]*"' || echo "guard after release: allow"
cat .mstack/scope-lock.log | sed 's/^[^ ]* /  log: /'

echo "#### remember"
R="$CORE/skills/remember/scripts/record.py"
python3 "$R" find database choice; echo "exit $?"
python3 "$R" add --text "Store all timestamps in UTC in the database." --why "The team works in three time zones and local times caused two bugs." --scope data | tail -2; echo "exit $?"
python3 "$R" add --text "All timestamps are stored in UTC in the database." --why "Three time zones caused bugs with local times."; echo "exit $? (expect 1: near duplicate)"
python3 "$R" add --text "The deploy password is hunter2-prod-9921 for staging." --why "So that nobody has to ask for it again."; echo "exit $? (expect 1: secret)"
python3 "$R" add --text "Too short" --why "x"; echo "exit $? (expect 2)"
OLD=$(python3 "$R" list | awk '{print $1}' | head -1)
python3 "$R" add --text "Store timestamps as UTC and also keep the user's zone name in a second column." --why "Reports need the local day, which UTC alone cannot give." --supersedes "$OLD" | tail -3; echo "exit $?"
python3 "$R" list
python3 "$R" check; echo "exit $?"
python3 "$R" --type lesson add --text "Run the migration on a copy of real data before running it on staging." --why "The last migration passed on test data and failed on real rows with null emails." | tail -2
python3 "$R" find timestamps zone
ls docs

echo "#### handoff"
H="$CORE/skills/handoff/scripts/handoff.py"
python3 "$H" show; echo "exit $? (expect 2)"
echo "x = 1" >> src/app.py
python3 "$H" write --goal "Add CSV export to the reports page." --state "The writer is done. The download button is not wired up. Tests were not run." --next "Wire the button to the writer." --next "Run the tests." --open "Should the export include archived rows?" --ref src/app.py; echo "exit $?"
python3 "$H" write --goal "g" --state "s" --next "n" --ref nope.md; echo "exit $? (expect 2: missing ref)"
FAKE="gh""p_abcdefghijklmnopqrstuvwxyz0123456789"   # fake token, split so the file itself holds no token
python3 "$H" write --goal "Use token $FAKE to push." --state "s" --next "n"; echo "exit $? (expect 1: secret)"
$git -c user.name=t -c user.email=t@t commit -qam "second"
python3 "$H" show | tail -5

echo "#### debrief"
D="$CORE/skills/debrief/scripts/changes.py"
python3 "$D" summary | head -12; echo "..."
python3 "$D" start --task "tidy docs" --scope docs; echo "exit $?"
echo "more" >> docs/guide.md; echo "y = 2" >> src/app.py; echo "new" > docs/new.md
python3 "$D" summary; echo "exit $?"

echo "#### mstack finder"
F="$CORE/skills/mstack/scripts/find.py"
python3 "$F" search is my work really finished before I commit | head -4
python3 "$F" search delete the old folders safely | head -2
python3 "$F" search file my income tax return; echo "exit $? (expect 0, no fit)"
python3 "$F" packs
python3 "$F" --map /nonexistent.json packs; echo "exit $? (expect 2)"

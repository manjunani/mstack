#!/bin/sh
# Script test for the land skill: preflight.py confirms the base, refuses a dirty tree and a failing suite,
# refuses after anything moved, and tests the merged result.
# Arguments: path to packs/dev, path of a NEW folder for the throwaway project (outside temporary folders).
DEV=$(cd "$1" && pwd); P="$2"; NAME=land
. "$DEV/tests/scripts/lib.sh"
F="$DEV/skills/land/scripts/preflight.py"
new_project "$P"
$G config user.name tester; $G config user.email tester@example.invalid; $G config commit.gpgsign false
SUITE="grep -q ok status.txt"

t 0 "help prints" python3 "$F" --help
t 2 "recheck with no snapshot is blocked" python3 "$F" recheck
t 1 "on the base branch there is nothing to land" python3 "$F" check --suite "true"
has "is the base branch itself"
$G switch -q -c feature
t 1 "a branch with no commits ahead fails" python3 "$F" check --suite "true"
echo "ok" > status.txt && $G add status.txt && $G commit -qm "add status"
echo "draft" > notes.txt
t 1 "an untracked file makes the tree dirty" python3 "$F" check --suite "$SUITE"
has "uncommitted changes: notes.txt"
mv notes.txt "$P.notes.txt"
t 2 "a base that is no branch is blocked" python3 "$F" check --base nope --suite "$SUITE"
t 2 "no suite given: not verified" python3 "$F" check
t 1 "a failing suite fails" python3 "$F" check --suite "false"
t 2 "a suite that cannot run is not verified" python3 "$F" check --suite "no-such-suite-xyz"
t 0 "clean branch, passing suite" python3 "$F" check --suite "$SUITE"
has "base: main (found by itself"
has "1 commits ahead of main, 0 behind"
t 0 "recheck right away passes" python3 "$F" recheck
echo "more" >> status.txt
t 1 "recheck catches a dirty tree" python3 "$F" recheck
$G add status.txt && $G commit -qm "more status"
t 1 "recheck catches a new commit" python3 "$F" recheck
has "branch tip"
t 0 "check again" python3 "$F" check --suite "$SUITE"
$G switch -q main && echo "other" > other.txt && $G add other.txt && $G commit -qm "main moves" && $G switch -q feature
t 1 "recheck catches a moved base" python3 "$F" recheck
has "base main"
t 0 "check again: behind is reported" python3 "$F" check --suite "$SUITE"
has "1 behind"
t 2 "merged while not on the base is blocked" python3 "$F" merged --suite "$SUITE"
$G switch -q main
t 1 "merged before the merge happened fails" python3 "$F" merged --suite "$SUITE"
$G merge -q --no-edit feature
t 1 "merged: a failing suite on the merged result fails" python3 "$F" merged --suite "false"
t 0 "merged: suite passes, branch is safe to delete" python3 "$F" merged --suite "$SUITE"
has "git branch -d feature"
same "preflight changed no branch" "$($G branch --list feature | wc -l | tr -d ' ')" "1"
mkdir "$P.nogit" && cd "$P.nogit" || exit 9
t 2 "outside a git repository is blocked" python3 "$F" recheck
finish

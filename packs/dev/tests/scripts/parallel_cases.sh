#!/bin/sh
# Script test for the parallel skill: lanes.py refuses overlapping file lists, creates worktrees and briefs,
# flags work outside a lane's list, merges in order, stops at a conflict, runs the suite on the merged tree,
# and removes only its own worktrees, never one with work that would be lost.
# Arguments: path to packs/dev, path of a NEW folder for the throwaway project (outside temporary folders).
DEV=$(cd "$1" && pwd); P="$2"; NAME=parallel
. "$DEV/tests/scripts/lib.sh"
L="$DEV/skills/parallel/scripts/lanes.py"; FX="$DEV/tests/scripts/fixtures"
new_project "$P"
$G config user.name tester; $G config user.email tester@example.invalid; $G config commit.gpgsign false
mkdir -p src/api src/ui tests docs
echo "api1" > src/api/a.py; echo "ui1" > src/ui/b.py; echo "shared1" > shared.py
echo "t" > tests/test_api.py; echo "t" > tests/test_ui.py; echo "one" > one.txt; echo "two" > two.txt
$G add . && $G commit -qm "base"
count() { $G worktree list | wc -l | tr -d ' '; }
clean() { $G status --porcelain -- . ':(exclude).mstack'; }

t 0 "help prints" python3 "$L" --help
t 2 "list with no run is not verified" python3 "$L" list
t 2 "a tasks file that does not exist is blocked" python3 "$L" check nope.json
t 1 "overlapping file lists are refused" python3 "$L" check "$FX/lanes_overlap.json"
has "OVERLAP api and ui: shared.py"
has "OVERLAP docs and docs2"
has "OVERLAP tests and onetest"
hasnt "OVERLAP api and docs"
t 1 "create refuses the same overlap" python3 "$L" create "$FX/lanes_overlap.json" --run r0
same "no worktree was created" "$(count)" "1"
t 1 "a bad tasks file fails" python3 "$L" check "$FX/lanes_bad.json"
has "task name 'Bad Name'"
has "task nofiles lists no files"
has "'../elsewhere/x.py' is not a path inside the project"
has "'/etc/hosts' is not a path inside the project"
has "task nogoal has no goal"
has "two tasks are named nogoal"
t 0 "independent tasks pass" python3 "$L" check "$FX/lanes_ok.json"

t 0 "create three lanes" python3 "$L" create "$FX/lanes_ok.json" --run r1
same "three worktrees were added" "$(count)" "4"
same "the main folder shows no new files to git" "$(clean)" ""
same "a brief exists for each lane" "$(ls .mstack/parallel/r1 | tr '\n' ' ')" "api.brief.md idle.brief.md run.json ui.brief.md "
t 2 "the same run name twice is blocked" python3 "$L" create "$FX/lanes_ok.json" --run r1
t 0 "list: no work yet" python3 "$L" list
has "no work yet"

W=.mstack/worktrees/r1
echo "api2" > $W/api/src/api/a.py && $G -C $W/api add src/api/a.py && $G -C $W/api commit -qm "api work"
echo "ui2" > $W/ui/src/ui/b.py; echo "shared-by-ui" > $W/ui/shared.py
$G -C $W/ui add src/ui/b.py shared.py && $G -C $W/ui commit -qm "ui work and a stray edit"
BEFORE=$($G rev-parse HEAD)
t 1 "list flags the file changed outside the lane's list" python3 "$L" list
has "outside its list: shared.py"
t 1 "merge refuses while a lane is outside its list" python3 "$L" merge --suite "true"
has "lane ui changed files outside its list: shared.py"
same "nothing was merged" "$($G rev-parse HEAD)" "$BEFORE"
echo "shared1" > $W/ui/shared.py && $G -C $W/ui add shared.py && $G -C $W/ui commit -qm "undo stray edit"
echo "draft" >> $W/api/src/api/a.py
t 1 "merge refuses while a lane has uncommitted work" python3 "$L" merge --suite "true"
has "lane api has uncommitted work"
t 1 "remove refuses a lane with uncommitted work" python3 "$L" remove --lane api
has "uncommitted work would be lost"
same "the lane folder is still there" "$(test -d $W/api && echo yes)" "yes"
echo "api2" > $W/api/src/api/a.py
t 1 "remove refuses lanes whose commits are not merged" python3 "$L" remove --lane ui
has "commits are not merged"

$G checkout -q -b elsewhere
t 2 "merge from another branch is blocked" python3 "$L" merge
$G checkout -q main
t 2 "merge without a suite: merged, but not verified" python3 "$L" merge
has "merged lane api"
has "merged lane ui"
has "no commits, nothing to merge"
t 1 "the suite failing on the merged tree is a fail" python3 "$L" merge --suite "false"
t 0 "the suite passing on the merged tree is a pass" python3 "$L" merge --suite "grep -q api2 src/api/a.py && grep -q ui2 src/ui/b.py"
has "already merged"

$G worktree add -q "$P.foreign" -b foreign
t 0 "remove takes away this run's lanes" python3 "$L" remove
has "lanes left in run r1: none"
same "only the main folder and the foreign worktree remain" "$(count)" "2"
same "the foreign worktree was not touched" "$(test -d "$P.foreign" && echo yes)" "yes"
same "the lane branches are gone" "$($G branch --list 'mstack/*' | wc -l | tr -d ' ')" "0"
t 0 "list shows the lanes as removed" python3 "$L" list
has "removed"

# a conflict: both lanes edit the same line of a file neither of them listed
t 0 "create two lanes for the conflict case" python3 "$L" create "$FX/lanes_conflict.json" --run r2
W=.mstack/worktrees/r2
echo "shared-one" > $W/one/shared.py && $G -C $W/one add shared.py && $G -C $W/one commit -qm "one edits shared"
echo "shared-two" > $W/two/shared.py && $G -C $W/two add shared.py && $G -C $W/two commit -qm "two edits shared"
t 1 "merge stops at the conflict and aborts that merge" python3 "$L" merge --allow-outside --suite "true"
has "conflict in lane two"
has "merged so far: one"
same "no merge is left half done" "$(test -e .git/MERGE_HEAD && echo merging || echo none)" "none"
same "the folder is clean after the aborted merge" "$(clean)" ""
t 1 "remove: the merged lane goes, the unmerged one is refused" python3 "$L" remove
has "one: removed"
has "two: REFUSED"
t 2 "discarding needs the lane named twice" python3 "$L" remove --lane two --discard-unmerged one
t 0 "discard on request, with the lane's name repeated" python3 "$L" remove --lane two --discard-unmerged two
has "the branch was at"
same "back to the main folder and the foreign worktree" "$(count)" "2"
same "the worktree folders are git-ignored" "$($G status --porcelain --ignored .mstack/parallel | cut -c1-2)" "!!"
$G worktree remove "$P.foreign"
mkdir "$P.nogit" && cd "$P.nogit" || exit 9
t 2 "outside a git repository is blocked" python3 "$L" check "$FX/lanes_ok.json"
finish

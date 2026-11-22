#!/bin/sh
# Script test for the review skill: review.py builds a package for an exact range, rejects findings that do
# not match the source, handles uncommitted changes, and checks answers to incoming review comments.
# Arguments: path to packs/dev, path of a NEW folder for the throwaway project (outside temporary folders).
DEV=$(cd "$1" && pwd); P="$2"; NAME=review
. "$DEV/tests/scripts/lib.sh"
R="$DEV/skills/review/scripts/review.py"; FX="$DEV/tests/scripts/fixtures"
new_project "$P"
mkdir -p src
i=1; while [ $i -le 20 ]; do echo "v$i = $i" >> src/util.py; i=$((i + 1)); done
printf 'def check(token, stored):\n    if not token:\n        return False\n    return token == stored\n' > src/auth.py
echo "gone = True" > src/gone.py
$G add src && $GC commit -qm "base"
BASE=$($G rev-parse HEAD)

t 2 "check before any package is blocked" python3 "$R" check "$FX/review_good.json"
t 0 "help prints" python3 "$R" --help
t 2 "on the default branch with no --base there is no range" python3 "$R" package
has "RESULT blocked"

$G checkout -q -b feature
sed -i.bak 's/^v15 = 15$/v15 = 150/' src/util.py && rm src/util.py.bak
printf 'def read_token(raw):\n    token = raw.strip()\n    return token\n' > src/new.py
$G rm -q src/gone.py
$G add src && $GC commit -qm "change util, add new"
printf 'def check(token, stored):\n    if token is None:\n        return False\n    return token == stored\n' > src/auth.py
$G add src && $GC commit -qm "auth: only None is empty"
HEAD=$($G rev-parse HEAD)

t 2 "a base that is no commit is blocked" python3 "$R" package --base no-such-branch
t 0 "package for the branch against main (base found by itself)" python3 "$R" package
has "range: $BASE..$HEAD"
has "2 commits"
has "4 files"
has "suggested depth: full (paths that need care: src/auth.py)"
PKG=".mstack/review/$(cat .mstack/review/current)"
same "the package holds diff, files, commits and meta" "$(ls "$PKG" | tr '\n' ' ')" "commits.txt diff.patch files.txt package.json "
same "the diff in the package is the real diff" "$(grep -c '^+v15 = 150' "$PKG/diff.patch")" "1"

t 0 "findings that match the source stand" python3 "$R" check "$FX/review_good.json"
has "kept     [important] src/util.py:15"
has "findings that stand: 0 critical, 1 important, 1 minor"
has "not judged: performance"

t 1 "findings that do not match the source are rejected" python3 "$R" check "$FX/review_bad.json"
has "REJECTED finding 1 (README.md:1): README.md is not one of the 4 files in the range"
has "REJECTED finding 2 (src/util.py:2): line 2 is outside the changed parts of src/util.py (changed: 12-18)"
has "REJECTED finding 3 (src/util.py:15): the quoted text is not at src/util.py:15; that line reads: v15 = 150"
has "REJECTED finding 4 (src/util.py:15): severity 'blocker' is not one of"
has "REJECTED finding 5 (src/util.py:15): field 'fix' is missing"
has "REJECTED finding 6 (src/gone.py:1): src/gone.py was deleted in the range"
has "kept     [important] src/util.py:15  this one is right"
has "6 of 7 findings do not match the source"

t 0 "a review with no findings is a pass" python3 "$R" check "$FX/review_none.json"
has "no findings. coverage: 4 files at depth full"
t 1 "a review that does not say what it left out fails" python3 "$R" check "$FX/review_nolist.json"
echo "not json" > .mstack/broken.json
t 2 "a findings file that is not JSON is blocked" python3 "$R" check .mstack/broken.json
t 0 "a range with no difference: nothing to review" python3 "$R" package --base feature
has "nothing to review"

# answers to review comments someone else left
sed -i.bak 's/^v15 = 150$/v15 = 15/' src/util.py && rm src/util.py.bak
t 0 "answers that hold pass" python3 "$R" feedback "$FX/feedback_good.json" --since "$HEAD"
has "1 accepted, 1 pushed back, 0 unclear"
t 1 "answers that do not hold are rejected" python3 "$R" feedback "$FX/feedback_bad.json" --since "$HEAD"
has "REJECTED answer 1: accepted, but README.md did not change"
has "REJECTED answer 2: a push-back has to cite the code"
has "REJECTED answer 3: the push-back cites a place that is not there: src/auth.py has 4 lines, not 400"
has "REJECTED answer 4: accepted, but no changed file is named"
has "REJECTED answer 5: needs id, comment, verdict and reason"
has "REJECTED answer 6: the comment points at a place that is not there"
has "REJECTED answer 7: verdict 'wontfix'"
t 2 "an unclear comment blocks" python3 "$R" feedback "$FX/feedback_unclear.json" --since "$HEAD"
has "Ask the reviewer"
t 2 "--since has to be a commit" python3 "$R" feedback "$FX/feedback_good.json" --since no-such-ref

# uncommitted changes, with a file git does not track yet
echo "DRAFT = True" > src/draft.py
t 0 "package for uncommitted changes" python3 "$R" package --working
has "range: uncommitted changes against HEAD"
has "src/draft.py"
has "suggested depth: light"
t 0 "a finding in a new untracked file stands" python3 "$R" check "$FX/review_working.json"
echo "DRAFT = False" > src/draft.py
t 2 "the package is stale once the working folder changes" python3 "$R" check "$FX/review_working.json"
has "build the package again"

same "the review folder is git-ignored" "$($G status --porcelain --ignored .mstack/review | cut -c1-2)" "!!"
mkdir "$P.nogit" && cd "$P.nogit" || exit 9
t 2 "outside a git repository is blocked" python3 "$R" package --working
finish

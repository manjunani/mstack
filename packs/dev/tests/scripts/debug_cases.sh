#!/bin/sh
# Script test for the debug skill: case.py through a whole case. The order is enforced (no fix before a
# failing reproduction and a confirmed hypothesis), the counter stops at three failed fixes, the cause has
# to cite a real line, and clean-run tells committed bugs from uncommitted ones without touching the folder.
# Arguments: path to packs/dev, path of a NEW folder for the throwaway project (outside temporary folders).
DEV=$(cd "$1" && pwd); P="$2"; NAME=debug
. "$DEV/tests/scripts/lib.sh"
C="$DEV/skills/debug/scripts/case.py"
new_project "$P"
mkdir -p src tests
: > src/__init__.py
printf 'def pages(total, size):\n    return total // size\n' > src/pager.py
printf 'def label(n):\n    return "page %%d" %% n\n' > src/other.py
printf 'import sys\nsys.path.insert(0, ".")\nfrom src.pager import pages\nassert pages(10, 3) == 4, "pages(10, 3) is %%d" %% pages(10, 3)\n' > tests/repro.py
printf 'import sys\nsys.path.insert(0, ".")\nfrom src.other import label\nassert label(2) == "page 2", "label is %%r" %% label(2)\n' > tests/repro2.py
$G add src tests && $GC commit -qm "pager"
sum() { shasum -a 256 "$1" | cut -d' ' -f1; }

t 0 "help prints" python3 "$C" --help
t 2 "status with no case is not verified" python3 "$C" status
t 2 "run with no case is blocked" python3 "$C" run
t 2 "a symptom of one word is refused" python3 "$C" open --symptom "broken" --repro "python3 tests/repro.py"
t 0 "open a case" python3 "$C" open --name pager --symptom "pages(10, 3) returns 3 but 10 items need 4 pages" --repro "python3 tests/repro.py" --expect-text "AssertionError"
t 2 "the same name twice is refused" python3 "$C" open --name pager --symptom "pages(10, 3) returns 3 but should be 4" --repro "true"
t 2 "fix before the reproduction was seen failing is blocked" python3 "$C" fix "use ceiling division" --hypothesis 1
has "has not been seen failing"
t 0 "run: the reproduction fails on the symptom" python3 "$C" run
has "FAILS on the stated symptom"
t 2 "fix without a confirmed hypothesis is blocked" python3 "$C" fix "use ceiling division" --hypothesis 1
has "is not confirmed"
t 2 "a hypothesis of two words is refused" python3 "$C" hypo add "bad math"
t 0 "hypothesis recorded" python3 "$C" hypo add "pages() uses floor division at src/pager.py:2, so a partial last page is dropped"
t 2 "evidence of one word is refused" python3 "$C" hypo rule 1 confirmed --evidence "checked"
t 2 "fix for an open hypothesis is still blocked" python3 "$C" fix "use ceiling division" --hypothesis 1
t 0 "hypothesis confirmed with evidence" python3 "$C" hypo rule 1 confirmed --evidence "printed total // size for (10, 3): 3; the ceiling is 4"

t 0 "fix attempt 1 recorded" python3 "$C" fix "added 1 when size is odd" --hypothesis 1
t 2 "a second fix before the first was checked is blocked" python3 "$C" fix "another idea" --hypothesis 1
t 1 "run: attempt 1 did not work" python3 "$C" run
has "1 of 3 failed"
t 0 "fix attempt 2 recorded" python3 "$C" fix "rounded the division" --hypothesis 1
t 1 "run: attempt 2 did not work" python3 "$C" run
t 0 "fix attempt 3 recorded" python3 "$C" fix "swapped the arguments" --hypothesis 1
t 1 "run: attempt 3 did not work" python3 "$C" run
has "3 fixes have failed. Stop fixing"
t 2 "a fourth fix is refused" python3 "$C" fix "one more idea" --hypothesis 1
has "No fourth fix"
t 2 "status is blocked at three failed fixes" python3 "$C" status
t 2 "a rethink note of two words is refused" python3 "$C" rethink --note "try again"
t 0 "rethink recorded with the user's decision" python3 "$C" rethink --note "user confirmed the reproduction is right; the earlier fixes edited the wrong function"
printf 'def pages(total, size):\n    return -(-total // size)\n' > src/pager.py
t 0 "fix attempt 4 is allowed after the rethink" python3 "$C" fix "ceiling division in pages()" --hypothesis 1
t 0 "run: the reproduction passes with the fix" python3 "$C" run
has "PASSES with fix attempt 4"

t 2 "close without file:line is blocked" python3 "$C" close --cause "floor division drops the last page"
t 1 "close citing a line that does not exist fails" python3 "$C" close --cause "src/pager.py:99 used floor division"
has "has 2 lines"
t 1 "close citing a file that does not exist fails" python3 "$C" close --cause "src/nope.py:1 used floor division"
echo "# comment" >> src/pager.py
t 2 "close after the code changed again is not verified" python3 "$C" close --cause "src/pager.py:2 used floor division"
has "code changed after the last passing run"
t 0 "run again on the changed code" python3 "$C" run --expect pass
t 0 "close with the cause" python3 "$C" close --cause "src/pager.py:2 used floor division, so 10 items in pages of 3 gave 3 pages; tests/repro.py:4 shows it"
t 0 "status of a closed case passes" python3 "$C" status
has "fix attempt 4 [worked]"
t 2 "run on a closed case is blocked" python3 "$C" run
$G add src && $GC commit -qm "fix pages"

t 0 "open: a command that does not show the bug" python3 "$C" open --name ghost --symptom "the page count is wrong on the last page" --repro "true"
t 1 "run: not reproduced" python3 "$C" run
has "not reproduced"
t 0 "open: a command that fails for another reason" python3 "$C" open --name other --symptom "the page count is wrong on the last page" --repro "python3 -c 'import no_such_module_xyz'" --expect-text "AssertionError"
t 1 "run: a different failure is not the symptom" python3 "$C" run
has "another failure"
t 0 "open: a command that cannot run" python3 "$C" open --name missing --symptom "the page count is wrong on the last page" --repro "no-such-command-xyz"
t 2 "run: not verified" python3 "$C" run
t 0 "open: diagnosis only" python3 "$C" open --name diag --symptom "the label shows the wrong page number" --repro "false"
t 0 "run: fails" python3 "$C" run
t 0 "close as diagnosis only, no fix" python3 "$C" close --diagnosis-only --cause "src/other.py:2 formats the number; the caller passes an index that starts at 0"
has "diagnosis only"

# clean-run: a bug that lives only in an uncommitted change
printf 'def label(n):\n    return "page %%d" %% (n + 1)\n' > src/other.py
BROKEN=$(sum src/other.py)
t 0 "open: a bug caused by an uncommitted change" python3 "$C" open --name local --symptom "label(2) says page 3 instead of page 2" --repro "python3 tests/repro2.py" --expect-text "AssertionError"
t 0 "run: fails in the working folder" python3 "$C" run
t 0 "clean-run: passes on committed code, so the cause is local" python3 "$C" clean-run
has "PASSES on committed code alone"
has "src/other.py"
same "clean-run did not touch the working file" "$(sum src/other.py)" "$BROKEN"
same "the clean checkout was removed again" "$($G worktree list | wc -l | tr -d ' ')" "1"
$G add src && $GC commit -qm "break label"
t 0 "clean-run: after the change is committed it fails on committed code too" python3 "$C" clean-run
has "fails the same way on committed code alone"
t 2 "clean-run without --expect-text cannot tell which failure it sees" python3 "$C" clean-run --name diag
same "still only one worktree" "$($G worktree list | wc -l | tr -d ' ')" "1"
same "the case folder is git-ignored" "$($G status --porcelain --ignored .mstack/debug | cut -c1-2)" "!!"
finish

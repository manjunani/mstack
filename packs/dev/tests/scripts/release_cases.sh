#!/bin/sh
# Script test for the release skill: cut.py finds the exact range since the last tag, lists migrations and
# config, writes the release file without overwriting, and refuses until a rollback step is written.
# Arguments: path to packs/dev, path of a NEW folder for the throwaway project (outside temporary folders).
DEV=$(cd "$1" && pwd); P="$2"; NAME=release
. "$DEV/tests/scripts/lib.sh"
R="$DEV/skills/release/scripts/cut.py"
new_project "$P"
$G config user.name tester; $G config user.email tester@example.invalid; $G config commit.gpgsign false
$G tag -a v1.0.0 -m "1.0.0"
OLD=$($G rev-parse HEAD)

t 0 "help prints" python3 "$R" --help
t 2 "nothing since the last tag is blocked" python3 "$R" range
mkdir -p src migrations config
echo "x" > src/app.py && $G add src && $G commit -qm "feat: export to csv"
echo "create table t (id int);" > migrations/0002_add_t.sql && $G add migrations && $G commit -qm "fix: add the missing table"
echo "debug: false" > config/app.yml && echo '{}' > package.json && $G add config package.json && $G commit -qm "update settings"
HEAD=$($G rev-parse HEAD)
t 0 "range since v1.0.0 with full ids" python3 "$R" range
has "range: $OLD..$HEAD"
has "3 commits"
has "migration files in the range: migrations/0002_add_t.sql"
has "config files in the range: config/app.yml"
has "dependencies files in the range: package.json"
t 2 "a version that is not a version is blocked" python3 "$R" draft banana
t 0 "draft writes the release file" python3 "$R" draft v1.1.0
F=.mstack/release/v1.1.0.md
has "wrote"
same "notes are grouped" "$(grep -c '^### ' $F)" "3"
t 2 "draft never overwrites" python3 "$R" draft v1.1.0
t 1 "ready refuses while the rollback is the placeholder" python3 "$R" ready v1.1.0
has "holds no real step"
printf 'Run the deploy again with the v1.0.0 image from the release page.\n' >> $F
t 1 "ready refuses a rollback that ignores the migration" python3 "$R" ready v1.1.0
has "does not say what happens to the database"
printf 'Before that, reverse migration 0002 with the down script; table t holds no data yet.\n' >> $F
t 0 "ready passes with a real rollback" python3 "$R" ready v1.1.0
has "tag command (not run): git tag -a v1.1.0 $HEAD"
same "no tag was made by the script" "$($G tag --list v1.1.0)" ""
echo "late" >> src/app.py
t 1 "a dirty tree fails" python3 "$R" ready v1.1.0
$G add src && $G commit -qm "fix: late change"
t 1 "the range moved after the draft" python3 "$R" ready v1.1.0
has "the range moved since the draft"
$G tag -a v1.1.0 -m "made by hand"
t 1 "an existing tag fails" python3 "$R" ready v1.1.0
has "exists already"
t 2 "ready without a release file is blocked" python3 "$R" ready v9.9.9
t 0 "--since picks another start" python3 "$R" range --since "$OLD"
mkdir "$P.nogit" && cd "$P.nogit" || exit 9
t 2 "outside a git repository is blocked" python3 "$R" range
finish

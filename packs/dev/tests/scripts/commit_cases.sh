#!/bin/sh
# Script test for the commit skill: gate.py lists and groups a mixed tree, finds staged secrets and conflict
# markers with redacted output, honours only waivers with a reason, lints messages, warns on the default
# branch, and checks what the last commit holds.
# Arguments: path to packs/dev, path of a NEW folder for the throwaway project (outside temporary folders).
DEV=$(cd "$1" && pwd); P="$2"; NAME=commit
. "$DEV/tests/scripts/lib.sh"
C="$DEV/skills/commit/scripts/gate.py"; FX="$DEV/tests/scripts/fixtures"
new_project "$P"
$G config user.name tester; $G config user.email tester@example.invalid; $G config commit.gpgsign false
mkdir -p src tests docs
echo "x = 1" > src/app.py && $G add src && $G commit -qm "feat: add app module"
for i in 1 2 3 4 5; do echo "$i" >> docs/log.md; $G add docs; $G commit -qm "docs: note number $i in the log"; done

t 0 "help prints" python3 "$C" --help
t 0 "tree with nothing changed" python3 "$C" tree
has "nothing to commit"
t 2 "scan with nothing staged is not verified" python3 "$C" scan
python3 "$FX/make_secrets.py" . > /dev/null
echo "y = 2" >> src/app.py; echo "t" > tests/test_app.py; echo "more" >> docs/log.md; echo '{}' > package.json
mkdir -p dist && echo "bundle" > dist/app.min.js
t 0 "tree lists files, kinds and holds" python3 "$C" tree
has "HOLD BACK: looks like a secret file"
has "HOLD BACK?: looks generated"
has "src: src/app.py"
hasnt ".env.example  HOLD"

$G add src/settings.py src/merge.py .env .env.example
t 1 "scan finds secrets, the secret file and the conflict markers" python3 "$C" scan
has "src/settings.py:2  aws-access-key-id  AKIA… (20 characters)"
has "github-token"
has ".env  secret-file"
has "src/merge.py:2  conflict-marker"
has "src/merge.py:6  conflict-marker"
hasnt "IOSFODNN7"
hasnt "changeme-example"
hasnt "os.environ"
hasnt ".env.example  secret-file"
hasnt "s3cr3t"

$G restore --staged .env src/merge.py
mkdir -p .mstack
printf '{"waivers": [{"file": "src/settings.py", "rule": "aws-access-key-id", "reason": "ok"}]}' > .mstack/commit-waivers.json
t 1 "a waiver without a reason is ignored" python3 "$C" scan
has "waivers have no real reason"
printf '{"waivers": [{"file": "src/settings.py", "rule": "aws-access-key-id", "reason": "the public sample key from the vendor docs"}, {"file": "src/settings.py", "rule": "github-token", "reason": "fake token used by the parser test fixture"}]}' > .mstack/commit-waivers.json
t 0 "waivers with reasons let the scan pass" python3 "$C" scan
has "waived src/settings.py:2  aws-access-key-id"
$G restore --staged src/settings.py .env.example

$G add src/app.py tests/test_app.py
t 1 "a vague subject fails" python3 "$C" msg -m "fix"
has "does not say what changed"
t 1 "subject and body without a blank line fail" python3 "$C" msg -m "$(printf 'feat: add the second value\nbody right away')"
t 1 "a secret in the message fails" python3 "$C" msg --file "$FX/commit_msg_secret.txt"
t 0 "a plain subject passes with a style warning" python3 "$C" msg -m "Add the second value to the app"
has "look like 'type: subject'"
t 0 "a subject in the repository's style passes" python3 "$C" msg -m "feat: add the second value to the app"
hasnt "warn"
t 2 "msg without a message is blocked" python3 "$C" msg

t 0 "branch warns on the default branch" python3 "$C" branch
has "WARN on the default branch 'main'"
$G switch -q -c work
t 0 "branch on a work branch has no warning" python3 "$C" branch
hasnt "WARN"
t 0 "check: branch, scan and message pass together" python3 "$C" check -m "feat: add the second value to the app"
$G commit -qm "feat: add the second value to the app"
t 0 "last: the commit holds exactly the meant files" python3 "$C" last --files src/app.py tests/test_app.py
echo "z = 3" >> src/app.py; echo "oops" >> docs/log.md; $G add src/app.py docs/log.md; $G commit -qm "feat: add a third value to the app"
t 1 "last: a file that slipped in is caught" python3 "$C" last --files src/app.py
has "in the commit but not meant to be: docs/log.md"
$G add src/merge.py
t 1 "check fails on conflict markers even with a good message" python3 "$C" check -m "feat: merge the two values"
same "gate.py staged and committed nothing itself" "$($G diff --cached --name-only)" "src/merge.py"
mkdir "$P.nogit" && cd "$P.nogit" || exit 9
t 2 "outside a git repository is blocked" python3 "$C" scan
finish

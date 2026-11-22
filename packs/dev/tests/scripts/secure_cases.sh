#!/bin/sh
# Script test for the secure skill: scan.py scans the change for secrets (redacted), gives each check a
# status, runs the audit tool only with --allow-network, and never calls a pass what it could not check.
# The npm used here is a stand-in from fixtures/fakebin, so no network is used.
# Arguments: path to packs/dev, path of a NEW folder for the throwaway project (outside temporary folders).
DEV=$(cd "$1" && pwd); P="$2"; NAME=secure
. "$DEV/tests/scripts/lib.sh"
S="$DEV/skills/secure/scripts/scan.py"; FX="$DEV/tests/scripts/fixtures"
new_project "$P"
$G config user.name tester; $G config user.email tester@example.invalid; $G config commit.gpgsign false

t 0 "help prints" python3 "$S" --help
t 0 "an empty change is a pass with the reason" python3 "$S" run
has "the change is empty"
printf 'def handler(request):\n    return request.args.get("q")\n' > app.py
t 0 "a clean change with no manifest passes" python3 "$S" run
has "secrets                ran"
has "no lock or manifest file"
printf 'import subprocess\ndef run(cmd):\n    subprocess.run(cmd, shell=True)\n' > tool.py
t 0 "surface lists the shell call" python3 "$S" run
has "tool.py: shell"
python3 "$FX/make_secrets.py" . > /dev/null
t 1 "secrets in the change fail, redacted" python3 "$S" run
has "aws-access-key-id  AKIA… (20 characters)"
has ".env  secret-file"
hasnt "IOSFODNN7"
hasnt "s3cr3t"
$G add app.py && $G commit -qm "app"
t 0 "--staged sees only the index: empty index, nothing found" python3 "$S" run --staged
has "scope: staged change; 0 files"
rm .env src/settings.py src/merge.py .env.example tool.py
echo '{}' > package-lock.json
t 2 "npm not on PATH: not available" env PATH=/usr/bin:/bin python3 "$S" run
has "audit npm"
has "not available"
t 2 "npm present but no permission for the network: not run" env PATH="$FX/fakebin:/usr/bin:/bin" python3 "$S" run
has "--allow-network"
t 0 "the audit runs with --allow-network and reports clean" env PATH="$FX/fakebin:/usr/bin:/bin" python3 "$S" run --allow-network
has "audit npm              ran"
t 1 "the audit reports a vulnerability" env FAKE_AUDIT=vuln PATH="$FX/fakebin:/usr/bin:/bin" python3 "$S" run --allow-network
has "Prototype Pollution"
t 0 "detect shows the audit command" env PATH="$FX/fakebin:/usr/bin:/bin" python3 "$S" detect
has "npm audit"
$G add package-lock.json && $GC commit -qm "lock"
$G switch -q -c work && echo "x = 1" > b.py && $G add b.py && $GC commit -qm "b"
t 2 "--base scopes to the branch; audit still not run without network" env PATH="$FX/fakebin:/usr/bin:/bin" python3 "$S" run --base main
has "1 files"
t 2 "--base that is no commit is blocked" python3 "$S" run --base nope
mkdir "$P.nogit" && cd "$P.nogit" || exit 9
t 2 "outside a git repository is blocked" python3 "$S" run
finish

#!/bin/sh
# Exercise the qa-run scripts in a throwaway project.
# Arguments: path to packs/test, path of a NEW folder to create the project in (outside temporary folders).
PACK=$(cd "$1" && pwd); P="$2"
[ -e "$P" ] && { echo "refusing: $P already exists"; exit 9; }
. "$PACK/tests/scripts/lib.sh"
S="$PACK/skills/qa-run/scripts/server.py"
R="$PACK/skills/qa-run/scripts/report.py"
mkdir -p "$P/shots" && cd "$P" || exit 9
P=$(pwd)
git=/usr/bin/git
echo "<h1>shop</h1>" > index.html
$git init -q -b main && $git add -A && $git -c user.name=t -c user.email=t@t commit -qm first
echo "<h1>shop</h1><form>cart</form>" > index.html
echo "body{}" > cart.css
PORT=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')

echo "#### server.py"
t 2 "status with nothing started" python3 "$S" status
t 2 "stop a name that was never started" python3 "$S" stop --name web
t 2 "start with a program that does not exist" python3 "$S" start --name web --port "$PORT" -- no-such-program-xyz
has "program not found" "says which program is missing"
t 1 "start a command that exits at once" python3 "$S" start --name web --port "$PORT" --timeout 10 -- python3 -c "import sys; print('boom: config missing'); sys.exit(3)"
has "boom: config missing" "shows the log of the dead command"
t 1 "start a command that never opens the port" python3 "$S" start --name web --port "$PORT" --timeout 2 -- python3 -c "import time; time.sleep(30)"
has "did not open within" "names the timeout"
t 0 "start a real server and wait for the port" python3 "$S" start --name web --port "$PORT" --http-path /index.html -- python3 -m http.server "$PORT" --bind 127.0.0.1
has "answered 200" "the app answered over HTTP, not only the port"
t 0 "status sees it running and listening" python3 "$S" status
t 2 "second start with the same name is refused" python3 "$S" start --name web --port "$PORT" -- python3 -m http.server "$PORT"
t 2 "start on a port that is already held is refused" python3 "$S" start --name other --port "$PORT" -- python3 -m http.server "$PORT"
has "another process holds it" "does not offer to kill the other process"
t 0 "wait sees the open port" python3 "$S" wait --port "$PORT" --timeout 5
t 0 "the page is really served" python3 -c "import urllib.request,sys; sys.exit(0 if b'cart' in urllib.request.urlopen('http://127.0.0.1:$PORT/index.html', timeout=5).read() else 1)"
t 0 "stop" python3 "$S" stop --name web
t 1 "wait fails once it is stopped" python3 "$S" wait --port "$PORT" --timeout 1
t 2 "stop again: nothing recorded" python3 "$S" stop --all

echo "#### report.py"
t 2 "check with no report" python3 "$R" check
t 0 "init records the diff scope" python3 "$R" init --title "cart form" --driver "host browser tool"
has "cart.css" "untracked file is in the scope"
has "index.html" "modified file is in the scope"
t 2 "second init refuses to overwrite" python3 "$R" init --title again
t 2 "check with no scenarios is not verified" python3 "$R" check
t 2 "a new scenario needs a name" python3 "$R" scenario S1 --state pass
t 0 "add S1" python3 "$R" scenario S1 --flow cart --name "add an item, cart shows 1 item"
t 0 "add S2" python3 "$R" scenario S2 --flow cart --name "remove the item, cart is empty"
t 0 "add S3" python3 "$R" scenario S3 --flow checkout --name "pay with a test card"
t 1 "check fails: scenarios have no final state" python3 "$R" check
has "S1: no final state" "names the scenario"
t 0 "S1 passes" python3 "$R" scenario S1 --state pass
t 2 "skipped needs a reason" python3 "$R" scenario S3 --state skipped
t 0 "S3 blocked with a reason" python3 "$R" scenario S3 --state blocked --reason "needs a payment sandbox key from the owner"
t 0 "issue with nothing but a title" python3 "$R" issue --scenario S2 --title "cart count stays at 1"
t 1 "check fails: the issue lacks steps, expected, actual, evidence" python3 "$R" check
has "no steps to reproduce" "steps"
has "no expected result" "expected"
has "no actual result" "actual"
has "no evidence file" "evidence"
t 2 "issue for an unknown scenario" python3 "$R" issue --scenario S9 --title x
t 2 "a scenario with an issue cannot be set to pass" python3 "$R" scenario S2 --state pass
# replace the bare issue with a complete one, first with evidence that does not exist
python3 - <<'EOF'
import json, pathlib
p = pathlib.Path(".mstack/qa/report.json"); d = json.loads(p.read_text())
d["issues"] = []; p.write_text(json.dumps(d))
EOF
t 0 "complete issue, evidence path missing on disk" python3 "$R" issue --scenario S2 --title "cart count stays at 1" --severity high --step "open /index.html" --step "add an item, then remove it" --expected "the cart shows 0 items" --actual "the cart shows 1 item" --evidence ../../shots/s2.png
t 1 "check fails: evidence file not found" python3 "$R" check
has "evidence file not found" "names the missing file"
: > shots/s2.png
t 1 "check fails: evidence file is empty" python3 "$R" check
has "evidence file is empty" "an empty file is not evidence"
printf 'PNG-bytes' > shots/s2.png
t 1 "report complete; result is fail because an issue exists" python3 "$R" check
has "1 issue(s) in 1 of 3 scenarios" "counts come from the file"
lacks "incomplete:" "no structural problem left"
t 0 "render to Markdown" python3 "$R" render
t 2 "render refuses to replace without --force" python3 "$R" render
t 0 "rendered file names the issue" grep -q "I1: cart count stays at 1" .mstack/qa/report.json .mstack/qa/report.md

echo "#### report.py: green scenarios, suite decides"
G=".mstack/qa/green.json"
t 0 "init a second report" python3 "$R" --report "$G" init --title "css only" --driver "host browser tool"
t 0 "one passing scenario" python3 "$R" --report "$G" scenario S1 --name "page loads with the new style" --state pass
t 2 "all pass but suite not recorded: not verified" python3 "$R" --report "$G" check
t 0 "record a red suite" python3 "$R" --report "$G" suite -- python3 -c "import sys; print('1 failed'); sys.exit(1)"
t 1 "green scenarios over a red suite is a fail" python3 "$R" --report "$G" check
has "test suite is red" "says why"
t 0 "record a green suite" python3 "$R" --report "$G" suite -- python3 -c "print('3 passed')"
t 0 "pass" python3 "$R" --report "$G" check
t 0 "suite marked as not run" python3 "$R" --report "$G" suite --not-run "no test command in this project"
t 2 "not run is not a pass" python3 "$R" --report "$G" check
t 0 "nothing to test, with a reason" python3 "$R" --report .mstack/qa/none.json init --title "readme typo" --driver none --nothing-to-test "only README.md changed"
t 0 "nothing to test is a pass with the reason" python3 "$R" --report .mstack/qa/none.json check
printf 'not json' > .mstack/qa/broken.json
t 2 "a broken report file is not verified" python3 "$R" --report .mstack/qa/broken.json check

finish

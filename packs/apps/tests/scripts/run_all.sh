#!/bin/sh
# Run every mstack-apps script test. Argument: a NEW folder under .testrun/ (one subfolder per test is made in it).
# Expected: each file ends with "<name>: N checks, N ok, 0 bad" and exit 0.
HERE=$(cd "$(dirname "$0")" && pwd); OUT="$1"
[ -z "$OUT" ] && { echo "usage: run_all.sh <new folder under .testrun/>"; exit 9; }
[ -e "$OUT" ] && { echo "refusing: $OUT exists"; exit 9; }
bad=0
for t in pngstat sim_proof sim_flow mac_release_verify tauri_preflight crash_read app_size app_release_notes ios_submit_check ios_a11y_check; do
  mkdir -p "$OUT"
  python3 "$HERE/${t}_cases.py" "$OUT/$t" > "$OUT/$t.log" 2>&1 || bad=1
  tail -1 "$OUT/$t.log"
done
exit $bad

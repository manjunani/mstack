#!/bin/sh
# Run every mstack-ops script test. Argument: a NEW folder (outside system temporary folders), for example
#   sh packs/ops/tests/scripts/run_all.sh .testrun/ops-all
# Each case file makes its own subfolder there and keeps its full output in <name>.txt.
# Expected: one line "<skill> cases: N run, 0 wrong" per skill and exit 0. The perf-check cases time real
# runs and retry a case up to three times on a busy machine; a retry is printed.
OUT="$1"
[ -n "$OUT" ] || { echo "usage: run_all.sh <new folder>"; exit 2; }
[ -e "$OUT" ] && { echo "refusing: $OUT already exists"; exit 2; }
mkdir -p "$OUT" || exit 2
HERE=$(cd "$(dirname "$0")" && pwd)
status=0
for name in deploy_check env_check migration_check restore_test perf_check ci_check ci_fix dep_upgrade rollback cost_watch log_triage; do
  python3 "$HERE/${name}_cases.py" "$OUT/$name" > "$OUT/$name.txt" 2>&1 || status=1
  grep -E "^BAD|needed [0-9] attempts| cases: " "$OUT/$name.txt" || { echo "BAD  $name: no summary line"; status=1; }
done
for f in "$HERE"/../../skills/*/scripts/*.py; do
  python3 "$f" --help > /dev/null 2>&1 || { echo "BAD  --help fails: $f"; status=1; }
done
echo "run_all: exit $status"
exit $status

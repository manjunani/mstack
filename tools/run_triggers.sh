#!/bin/sh
# Run the trigger and silence tests for the named skills of one pack and record the results.
# Usage: tools/run_triggers.sh <pack> <output folder> <cost ceiling per batch in USD> <skill> [<skill> ...]
# Each batch is one skill's ten fire or ten quiet cases, one run each, with the pack installed.
# Reports stay on this machine (--no-publish). Uses your own Claude sign-in and its limits.
pack="$1"; out="$2"; cap="$3"; shift 3
root="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$out"
python3 "$root/tools/build_evals.py" "$pack" || exit 1
files=""
for skill in "$@"; do
  for kind in fire quiet; do
    target="$out/$pack-$skill-$kind.json"
    claude plugin eval "$root/packs/$pack" --case "$skill.$kind.*" --ablation none --runs 1 -j 4 \
      --max-cost-usd "$cap" --trust-plugin --no-publish --json "$target" > "$out/$pack-$skill-$kind.log" 2>&1
    echo "$skill $kind: exit $?"
    [ -s "$target" ] && files="$files $target"
  done
done
# shellcheck disable=SC2086
python3 "$root/tools/record_results.py" "$pack" $files

#!/bin/sh
# Run full trigger tests for a list of packs and skills, one pack at a time.
# Usage: tools/run_lane.sh <list file> <output folder> <cost ceiling per batch in USD>
# Each line of the list file: <pack> <skill> [<skill> ...]
list="$1"; out="$2"; cap="$3"
root="$(cd "$(dirname "$0")/.." && pwd)"
while read -r pack skills; do
  [ -n "$pack" ] || continue
  # shellcheck disable=SC2086
  sh "$root/tools/run_triggers.sh" "$pack" "$out" "$cap" $skills
done < "$list"

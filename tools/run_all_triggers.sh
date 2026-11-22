#!/bin/sh
# Full trigger and silence tests for whole packs: every skill, all ten fire and ten quiet requests.
# Usage: tools/run_all_triggers.sh <output folder> <cost ceiling per batch in USD> <pack> [<pack> ...]
# Uses your own Claude sign-in and its limits. Reports stay on this machine.
out="$1"; cap="$2"; shift 2
root="$(cd "$(dirname "$0")/.." && pwd)"
for pack in "$@"; do
  skills=$(ls "$root/packs/$pack/skills")
  # shellcheck disable=SC2086
  sh "$root/tools/run_triggers.sh" "$pack" "$out" "$cap" $skills
done

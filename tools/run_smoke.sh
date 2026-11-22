#!/bin/sh
# Smoke test: N fire and N quiet prompts per skill for one pack, one run each, then record the results as "smoke".
# Usage: tools/run_smoke.sh <pack> <output folder> <cost ceiling in USD> [N, default 2]
# Uses your own Claude sign-in and its limits. Reports stay on this machine (--no-publish).
pack="$1"; out="$2"; cap="$3"; n="${4:-2}"
root="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$out"
python3 "$root/tools/build_evals.py" "$pack" --smoke "$n" || exit 1
target="$out/$pack-smoke.json"
claude plugin eval "$root/packs/$pack" --eval-dir evals-smoke --ablation none --runs 1 -j 4 \
  --max-cost-usd "$cap" --trust-plugin --no-publish --json "$target" > "$out/$pack-smoke.log" 2>&1
echo "$pack smoke: exit $?"
[ -s "$target" ] && python3 "$root/tools/record_results.py" "$pack" --smoke "$target"

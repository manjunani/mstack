#!/usr/bin/env python3
"""Copy test results from `claude plugin eval --json` output into a pack's tests/results.json.

  record_results.py PACK RESULT.json [RESULT.json ...]

Case names tell what was tested: <skill>.fire.NN, <skill>.quiet.NN, <skill>.task.NAME.
  trigger  how many fire cases started the skill
  silence  how many quiet cases started the skill (lower is better)
  benefit  how many tasks scored higher with the pack than without it
Results are only ever written by this script, from eval output. Exit 0 = recorded, 2 = nothing usable found.
"""
import argparse
import collections
import datetime
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import common  # noqa: E402


def failed(run):
    """A run that never really happened: usage limit, sign-in, network or API error.
    Running out of turns is a real outcome (the model did not start the skill), so it is not a failure."""
    error = str(run.get("error") or "")
    return bool(error) and "maximum number of turns" not in error


def mean(runs):
    return sum(r.get("score", 0) for r in runs) / len(runs) if runs else None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pack", help="pack folder name, for example core")
    parser.add_argument("files", nargs="+", type=pathlib.Path)
    parser.add_argument("--root", type=pathlib.Path, default=common.ROOT)
    parser.add_argument("--smoke", action="store_true", help="mark these results as a smoke test (a few prompts per skill)")
    args = parser.parse_args()

    counts = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0]))
    broken = collections.Counter()
    cost, version, runs_per_case = 0.0, "", set()
    for path in args.files:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("partial"):
            print(f"skipped {path.name}: the run was partial (cost ceiling or sign-in problem)")
            continue
        cost += data.get("costUsd", 0)
        version = data.get("claudeVersion", version)
        for case in data.get("cases", []):
            parts = case["name"].split(".")
            if len(parts) < 3 or parts[1] not in ("fire", "quiet", "task"):
                continue
            skill, kind = parts[0], parts[1]
            all_runs = case["arms"].get("with", [])
            with_runs = [r for r in all_runs if not failed(r)]
            broken[skill] += len(all_runs) - len(with_runs) + sum(1 for r in case["arms"].get("without", []) if failed(r))
            runs_per_case.add(len(all_runs))
            if not with_runs:
                continue
            case_passed = sum(1 for r in with_runs if r.get("passed")) * 2 > len(with_runs)  # majority of runs
            if kind == "fire":  # a fire case passes when the skill started
                counts[skill]["trigger"][0] += case_passed
                counts[skill]["trigger"][1] += 1
            elif kind == "quiet":  # a quiet case passes when the skill stayed quiet, so a failed one means it started
                counts[skill]["silence"][0] += not case_passed
                counts[skill]["silence"][1] += 1
            else:
                without = mean(case["arms"].get("without", []))
                if without is not None:
                    counts[skill]["benefit"][0] += mean(with_runs) > without
                    counts[skill]["benefit"][1] += 1
    if not counts:
        print("nothing usable found in the given files")
        return 2

    target = args.root / "packs" / args.pack / "tests" / "results.json"
    results = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
    skipped = []
    for skill in sorted(set(counts) | set(broken)):
        if broken[skill]:
            skipped.append(f"{skill} ({broken[skill]} runs failed to run)")
            continue
        kinds = counts[skill]
        entry = results.get(skill, {})
        if kinds["trigger"][1]:
            entry["trigger"] = f"{kinds['trigger'][0]}/{kinds['trigger'][1]}"
        if kinds["silence"][1]:
            entry["silence"] = f"{kinds['silence'][0]}/{kinds['silence'][1]}"
        if kinds["benefit"][1]:
            entry["benefit"] = f"{kinds['benefit'][0]}/{kinds['benefit'][1]}"
        if args.smoke:
            entry["kind"] = "smoke"
        else:
            entry.pop("kind", None)
        entry["runs"] = max(runs_per_case) if runs_per_case else 1
        entry["tested"] = datetime.date.today().isoformat()
        entry["with"] = f"Claude Code {version}"
        results[skill] = entry
        print(f"{skill}: " + ", ".join(f"{k} {v}" for k, v in entry.items()))
    for line in skipped:
        print(f"NOT RECORDED {line}: a usage limit, sign-in or API error stopped some runs; run this skill again")
    target.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {target.relative_to(args.root)} (usage in these files: about ${cost:.2f} at list price)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Decide pass or fail for an evaluation run against a saved baseline.

The results come from your own runner. This script calls no model. A results file is JSON lines,
one row per trial of one case:

  {"case": "refund-01", "trial": 1, "pass": true}
  {"case": "refund-01", "trial": 2, "score": 0.4}

Accepted names: case | case_id | id, trial | run | attempt (optional), pass | passed, score,
critical (optional, true marks a case that may not get worse).

Commands:
  summary <results>              per-case and overall pass rates of one file
  save <results>                 keep a file as the baseline in .mstack/eval-gate/baseline.jsonl
  compare --candidate <results>  compare a candidate with the baseline, case by case

compare averages the trials inside each case, pairs the cases of the two files, and reports the
difference with a 95% interval. It passes when no shared case got worse, or when the whole interval
stays above the allowed drop. It fails on a real drop, on a baseline case that is missing from the
candidate, and on a critical case that got worse. When the files cannot settle the question it says
so and gives the number of cases that would.

Exit codes: 0 = pass
            1 = fail
            2 = not verified (too few trials or cases, or the interval is too wide) or blocked (bad input)
The last line printed is the result.
"""
import argparse
import datetime
import hashlib
import json
import math
import pathlib
import sys

STATE = pathlib.Path(".mstack") / "eval-gate"
DEFAULTS = pathlib.Path(__file__).resolve().parent.parent / "references" / "defaults.json"
# Two-sided 95% points of Student's t distribution, by degrees of freedom. Mathematical constants.
T95 = [12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228, 2.201, 2.179, 2.160, 2.145, 2.131,
       2.120, 2.110, 2.101, 2.093, 2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042]
TRUE_WORDS = {"true", "pass", "passed", "yes", "ok", "1"}
FALSE_WORDS = {"false", "fail", "failed", "no", "0"}


class Blocked(Exception):
    """Input that cannot be used. Ends the run as blocked."""


def end(state, why=""):
    why = " ".join(str(why).split())  # the result stays on one line, whatever text it quotes
    print(f"RESULT {state}" + (f": {why}" if why else ""))
    return {"pass": 0, "fail": 1}.get(state, 2)


def t_point(df):
    if df < 1:
        return float("inf")
    if df <= 30:
        return T95[df - 1]
    if df <= 40:
        return 2.021
    if df <= 60:
        return 2.000
    if df <= 120:
        return 1.980
    return 1.960


def load_defaults():
    try:
        data = json.loads(DEFAULTS.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Blocked(f"the defaults file {DEFAULTS} cannot be read ({exc})")
    return {k: v for k, v in data.items() if isinstance(v, dict) and "value" in v}


def first(row, names):
    for name in names:
        if name in row and row[name] is not None:
            return row[name]
    return None


def as_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in TRUE_WORDS:
        return True
    if isinstance(value, str) and value.strip().lower() in FALSE_WORDS:
        return False
    return None


def read_results(path, pass_score):
    """Return {case: {"trials": [bool, ...], "critical": bool}}. Raises Blocked on unusable input."""
    path = pathlib.Path(path)
    if not path.is_file():
        raise Blocked(f"no results file at {path}")
    cases, bad, seen = {}, [], set()
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            bad.append(f"line {number}: not JSON")
            continue
        if not isinstance(row, dict):
            bad.append(f"line {number}: not an object")
            continue
        case = first(row, ("case", "case_id", "id"))
        if case is None or str(case).strip() == "":
            bad.append(f"line {number}: no case id")
            continue
        case = str(case)
        outcome = as_bool(first(row, ("pass", "passed")))
        if outcome is None:
            score = row.get("score")
            if isinstance(score, bool) or not isinstance(score, (int, float)) or math.isnan(score):
                bad.append(f"line {number}: case {case} has neither a pass value nor a numeric score")
                continue
            outcome = score >= pass_score
        trial = first(row, ("trial", "run", "attempt"))
        if trial is not None:
            if (case, str(trial)) in seen:
                bad.append(f"line {number}: case {case} trial {trial} appears twice")
                continue
            seen.add((case, str(trial)))
        entry = cases.setdefault(case, {"trials": [], "critical": False})
        entry["trials"].append(outcome)
        entry["critical"] = entry["critical"] or row.get("critical") is True
    if bad:
        shown = "; ".join(bad[:8]) + (f"; and {len(bad) - 8} more" if len(bad) > 8 else "")
        raise Blocked(f"{path} has {len(bad)} rows that cannot be used ({shown})")
    if not cases:
        raise Blocked(f"{path} holds no result rows")
    return cases


def rate(entry):
    return sum(entry["trials"]) / len(entry["trials"])


def kind(entry):
    r = rate(entry)
    return "passes every time" if r == 1 else "fails every time" if r == 0 else "unstable"


def overview(cases):
    rates = [rate(c) for c in cases.values()]
    counts = [len(c["trials"]) for c in cases.values()]
    return {
        "cases": len(cases),
        "trials": sum(counts),
        "fewest_trials": min(counts),
        "most_trials": max(counts),
        "overall": sum(rates) / len(rates),
        "every_time": sum(1 for r in rates if r == 1),
        "at_least_once": sum(1 for r in rates if r > 0),
        "unstable": sum(1 for r in rates if 0 < r < 1),
    }


def print_overview(label, cases):
    o = overview(cases)
    spread = f"{o['fewest_trials']}" if o["fewest_trials"] == o["most_trials"] else f"{o['fewest_trials']} to {o['most_trials']}"
    print(f"{label}: {o['cases']} cases, {o['trials']} trials ({spread} per case)")
    print(f"  overall pass rate (mean of the case rates): {o['overall']:.3f}")
    print(f"  passed every time: {o['every_time']} of {o['cases']}   passed at least once: {o['at_least_once']} of {o['cases']}   unstable: {o['unstable']}")
    return o


def short_cases(cases, min_trials):
    return sorted(name for name, c in cases.items() if len(c["trials"]) < min_trials)


def names(items, limit=8):
    items = list(items)
    return ", ".join(items[:limit]) + (f" and {len(items) - limit} more" if len(items) > limit else "")


def cmd_summary(args, defaults):
    cases = read_results(args.results, args.pass_score)
    print_overview(str(args.results), cases)
    print("  case                           trials  passed  rate   state")
    for name in sorted(cases):
        c = cases[name]
        print(f"  {name[:30]:<30} {len(c['trials']):>6}  {sum(c['trials']):>6}  {rate(c):.2f}   {kind(c)}{'  (critical)' if c['critical'] else ''}")
    short = short_cases(cases, args.min_trials)
    if short:
        return end("not verified", f"{len(short)} cases have fewer than {args.min_trials} trials ({names(short)}); run them again before using this file as a baseline")
    return end("pass", f"{len(cases)} cases, each with at least {args.min_trials} trials; nothing was compared")


def cmd_save(args, defaults):
    cases = read_results(args.results, args.pass_score)
    print_overview(str(args.results), cases)
    short = short_cases(cases, args.min_trials)
    if short:
        return end("not verified", f"not saved: {len(short)} cases have fewer than {args.min_trials} trials ({names(short)})")
    STATE.mkdir(parents=True, exist_ok=True)
    target = STATE / "baseline.jsonl"
    raw = pathlib.Path(args.results).read_bytes()
    if target.exists():
        if not args.replace:
            return end("blocked", f"a baseline already exists at {target}. Replacing it changes what every later run is compared with; ask the user, then run save again with --replace")
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        kept = STATE / f"baseline-{stamp}.jsonl"
        kept.write_bytes(target.read_bytes())
        print(f"the old baseline was kept as {kept}")
    target.write_bytes(raw)
    meta = {"saved": datetime.datetime.now().isoformat(timespec="seconds"), "from": str(args.results),
            "sha256": hashlib.sha256(raw).hexdigest(), "note": args.note or "", **overview(cases)}
    (STATE / "baseline.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(f"baseline saved to {target}")
    return end("pass", "baseline saved; nothing was compared")


def cmd_compare(args, defaults):
    baseline_path = pathlib.Path(args.baseline) if args.baseline else STATE / "baseline.jsonl"
    if not baseline_path.is_file():
        raise Blocked(f"no baseline at {baseline_path}. Run the evaluation on the version you trust and keep it with: gate.py save <results>")
    base = read_results(baseline_path, args.pass_score)
    cand = read_results(args.candidate, args.pass_score)
    used = [k for k in ("min_trials", "min_cases", "max_drop", "pass_score") if not defaults[k].get("verified")]
    print(f"note: {', '.join(used)} are mstack defaults, not measured values ({DEFAULTS.name}); the flags change them.")
    print(f"settings: min trials {args.min_trials}, min cases {args.min_cases}, allowed drop {args.max_drop:.3f}, pass score {args.pass_score}")
    print_overview(f"baseline  {baseline_path}", base)
    print_overview(f"candidate {args.candidate}", cand)

    retired = set(args.retired or [])
    unknown_retired = sorted(retired - set(base))
    if unknown_retired:
        raise Blocked(f"--retired names cases that are not in the baseline: {names(unknown_retired)}")
    common = sorted(set(base) & set(cand))
    missing = sorted(set(base) - set(cand) - retired)
    new = sorted(set(cand) - set(base))
    critical = {n for n in common if base[n]["critical"] or cand[n]["critical"]} | (set(args.critical or []) & set(common))
    unknown_critical = sorted(set(args.critical or []) - set(base) - set(cand))
    if unknown_critical:
        raise Blocked(f"--critical names cases that are in neither file: {names(unknown_critical)}")

    print(f"\ncases in both files: {len(common)}   missing from the candidate: {len(missing)}   new in the candidate: {len(new)}   retired by flag: {len(retired)}")
    rows, flips, lost, worse_critical = [], [], [], []
    for name in common:
        b, c = rate(base[name]), rate(cand[name])
        rows.append((name, b, c, c - b))
        if (b >= 0.5) != (c >= 0.5):
            flips.append((name, b, c))
        elif b == 1 and c < 1:
            lost.append((name, b, c))
        if name in critical and b == 1 and c < 1:
            worse_critical.append(name)
    if rows:
        print("  case                           baseline  candidate  change")
        for name, b, c, d in rows:
            mark = "  FLIPPED" if (b >= 0.5) != (c >= 0.5) else ""
            mark += "  critical" if name in critical else ""
            print(f"  {name[:30]:<30} {b:>8.2f}  {c:>9.2f}  {d:>+6.2f}{mark}")
    for name, b, c in flips:
        direction = "pass to fail" if b >= 0.5 else "fail to pass"
        print(f"FLIP {name}: {direction} ({b:.2f} to {c:.2f})")
    for name, b, c in lost:
        print(f"LESS STABLE {name}: passed every time in the baseline, {c:.2f} in the candidate")
    for name in missing:
        print(f"MISSING {name}: in the baseline, not in the candidate")
    for name in new:
        print(f"NEW {name}: only in the candidate, not compared")

    record = {"baseline": str(baseline_path), "candidate": str(args.candidate), "common": len(common),
              "missing": missing, "new": new, "retired": sorted(retired),
              "flipped": [{"case": n, "baseline": b, "candidate": c} for n, b, c in flips],
              "critical_worse": worse_critical}

    def finish(state, why):
        record.update(result=state, reason=why, when=datetime.datetime.now().isoformat(timespec="seconds"))
        STATE.mkdir(parents=True, exist_ok=True)
        out = STATE / "last-compare.json"
        out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        print(f"record written to {out}")
        return end(state, why)

    if missing:
        return finish("fail", f"{len(missing)} baseline cases are missing from the candidate ({names(missing)}). Run them, or name them with --retired if the user removed them on purpose")
    if worse_critical:
        return finish("fail", f"critical cases got worse: {names(worse_critical)}")
    short = sorted(set(short_cases({n: base[n] for n in common}, args.min_trials)) | set(short_cases({n: cand[n] for n in common}, args.min_trials)))
    if short:
        return finish("not verified", f"{len(short)} cases have fewer than {args.min_trials} trials in one of the files ({names(short)}); run them again")
    if len(common) < args.min_cases:
        return finish("not verified", f"only {len(common)} cases are in both files; at least {args.min_cases} are needed to tell a change from chance")

    diffs = [d for _, _, _, d in rows]
    n = len(diffs)
    mean = sum(diffs) / n
    sd = math.sqrt(sum((d - mean) ** 2 for d in diffs) / (n - 1)) if n > 1 else 0.0
    half = t_point(n - 1) * sd / math.sqrt(n)
    low, high = mean - half, mean + half
    base_overall = sum(b for _, b, _, _ in rows) / n
    cand_overall = sum(c for _, _, c, _ in rows) / n
    print(f"\noverall on the {n} shared cases: baseline {base_overall:.3f}, candidate {cand_overall:.3f}, difference {mean:+.3f}")
    print(f"95% interval of the difference: {low:+.3f} to {high:+.3f} (paired by case)")
    record.update(baseline_overall=base_overall, candidate_overall=cand_overall, difference=mean, interval=[low, high])

    tol = args.max_drop
    if min(diffs) >= 0:
        gained = sum(1 for d in diffs if d > 0)
        return finish("pass", f"no shared case got worse; {gained} improved, difference {mean:+.3f}")
    if low >= -tol:
        extra = f"; {len(flips)} cases flipped, read them" if flips else ""
        return finish("pass", f"difference {mean:+.3f}, and the interval stays above the allowed drop of {tol:.3f}{extra}")
    if high < 0 and mean < -tol:
        return finish("fail", f"the pass rate dropped by {-mean:.3f} (interval {low:+.3f} to {high:+.3f}), more than the allowed {tol:.3f}")
    gap = (mean + tol) if mean >= -tol else -mean
    if gap > 0 and sd > 0:
        needed = max(n + 1, math.ceil((1.96 * sd / gap) ** 2))
        hint = f"about {needed} cases with this much spread would settle it"
    else:
        hint = "more cases are needed"
    return finish("not verified", f"the sample is too small to tell: difference {mean:+.3f}, interval {low:+.3f} to {high:+.3f} crosses the allowed drop of {tol:.3f}; {hint}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    try:
        defaults = load_defaults()
        for key in ("min_trials", "min_cases", "max_drop", "pass_score"):
            if key not in defaults:
                raise Blocked(f"{DEFAULTS} has no entry '{key}'")
    except Blocked as exc:
        return end("blocked", str(exc))

    def common_flags(sub):
        sub.add_argument("--min-trials", type=int, default=defaults["min_trials"]["value"], help="trials each case needs (default %(default)s)")
        sub.add_argument("--pass-score", type=float, default=defaults["pass_score"]["value"], help="a row with a score and no pass value passes at or above this (default %(default)s)")

    subs = parser.add_subparsers(dest="command", required=True)
    s = subs.add_parser("summary", help="per-case and overall pass rates of one results file")
    s.add_argument("results")
    common_flags(s)
    s.set_defaults(run=cmd_summary)
    s = subs.add_parser("save", help="keep a results file as the baseline under .mstack/eval-gate/")
    s.add_argument("results")
    s.add_argument("--replace", action="store_true", help="replace an existing baseline (the old one is kept under a dated name)")
    s.add_argument("--note", help="one line on what this baseline is: model, prompt version, date")
    common_flags(s)
    s.set_defaults(run=cmd_save)
    s = subs.add_parser("compare", help="compare a candidate results file with the baseline")
    s.add_argument("--candidate", required=True, help="results file of the changed version")
    s.add_argument("--baseline", help="results file of the trusted version (default: .mstack/eval-gate/baseline.jsonl)")
    s.add_argument("--min-cases", type=int, default=defaults["min_cases"]["value"], help="cases needed in both files (default %(default)s)")
    s.add_argument("--max-drop", type=float, default=defaults["max_drop"]["value"], help="pass rate the candidate may lose, 0 to 1 (default %(default)s)")
    s.add_argument("--critical", nargs="+", metavar="CASE", help="cases that may not get worse at all")
    s.add_argument("--retired", nargs="+", metavar="CASE", help="baseline cases the user removed on purpose")
    common_flags(s)
    s.set_defaults(run=cmd_compare)
    args = parser.parse_args()
    if args.min_trials < 1 or getattr(args, "min_cases", 2) < 2 or not 0 <= getattr(args, "max_drop", 0) <= 1:
        return end("blocked", "--min-trials needs 1 or more, --min-cases 2 or more, --max-drop a value from 0 to 1")
    try:
        return args.run(args, defaults)
    except Blocked as exc:
        return end("blocked", str(exc))


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Time a command several times, keep the result as a baseline, and later say whether a change moved it.

  measure.py baseline --name NAME [--runs 7] [--warmup 1] [--replace] -- COMMAND [ARG ...]
      Runs COMMAND warmup + runs times, records the wall time of each counted run and saves
      .mstack/perf-check/NAME.json with the times, the median and the spread (the middle half of the runs).

  measure.py compare --name NAME [--goal faster|not-slower]
      Runs the SAME command with the same number of runs, and compares the two medians.
      The difference counts only when it is larger than the noise: the wider of the two spreads, and at
      least a small share of the baseline median (see references/noise.json).
        faster beyond noise       -> pass  (keep the change)
        slower beyond noise       -> fail  (revert the change)
        inside the noise          -> not verified for --goal faster; pass for --goal not-slower
        inside the noise, and the timings vary by more than the spread limit -> not verified for both goals

  measure.py show --name NAME     print the saved baseline

The command is run as given, without a shell, from --root. Its output is discarded unless it fails.
A command that exits non-zero is not a measurement: the script stops and shows its last lines.

Exit codes: 0 = pass, 1 = fail (slower beyond noise), 2 = not verified or blocked.
"""
import argparse
import datetime
import json
import pathlib
import platform
import statistics
import subprocess
import sys
import time

NOISE = pathlib.Path(__file__).resolve().parent.parent / "references" / "noise.json"
FALLBACK = {"min_runs": 5, "relative_floor_pct": 2, "max_spread_pct": 25}


def settings():
    """Return ({name: value}, [unverified names])."""
    try:
        data = json.loads(NOISE.read_text(encoding="utf-8"))
        return {k: data[k]["value"] for k in FALLBACK}, [k for k in FALLBACK if not data[k].get("verified")]
    except (OSError, ValueError, KeyError):
        return dict(FALLBACK), list(FALLBACK)


def blocked(text):
    print(f"blocked: {text}")
    return 2


def time_runs(command, root, runs, warmup, timeout):
    """Return (times in ms, None) or (None, reason)."""
    times = []
    for number in range(warmup + runs):
        begin = time.perf_counter()
        try:
            done = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError:
            return None, f"command not found: {command[0]}"
        except subprocess.TimeoutExpired:
            return None, f"run {number + 1} did not finish within {timeout} seconds"
        elapsed = (time.perf_counter() - begin) * 1000
        if done.returncode != 0:
            for line in (done.stdout + done.stderr).strip().splitlines()[-8:]:
                print("  | " + line)
            return None, f"the command exited {done.returncode} on run {number + 1}; a failing command cannot be measured"
        label = "warm-up" if number < warmup else f"run {number - warmup + 1}"
        print(f"  {label}: {elapsed:.1f} ms", flush=True)
        if number >= warmup:
            times.append(round(elapsed, 2))
    return times, None


def stats(times):
    q1, _, q3 = statistics.quantiles(times, n=4, method="inclusive")
    median = statistics.median(times)
    return {"median": round(median, 2), "q1": round(q1, 2), "q3": round(q3, 2), "spread": round(q3 - q1, 2),
            "min": min(times), "max": max(times), "spread_pct": round((q3 - q1) / median * 100, 1) if median else 0.0}


def describe(label, s):
    return f"{label}: median {s['median']} ms, spread {s['spread']} ms ({s['spread_pct']}% of the median), range {s['min']} to {s['max']} ms"


def cmd_baseline(args, folder, conf):
    command = args.command
    if not command:
        return blocked("give the command to time after --")
    if args.runs < conf["min_runs"]:
        return blocked(f"--runs must be at least {conf['min_runs']}; fewer runs cannot show the spread")
    path = folder / f"{args.name}.json"
    if path.exists() and not args.replace:
        old = json.loads(path.read_text(encoding="utf-8"))
        return blocked(f"a baseline named '{args.name}' exists (taken {old['when']}). Compare against it, or pass --replace to set it aside and take a new one.")
    print(f"timing: {' '.join(command)}  ({args.warmup} warm-up, {args.runs} counted runs)")
    times, problem = time_runs(command, args.root, args.runs, args.warmup, args.timeout)
    if problem:
        return blocked(problem)
    s = stats(times)
    folder.mkdir(parents=True, exist_ok=True)
    if path.exists():
        aside = folder / f"{args.name}.{datetime.datetime.now().strftime('%Y%m%dT%H%M%S')}.old.json"
        path.rename(aside)
        print(f"  the earlier baseline was kept as {aside.name}")
    record = {"name": args.name, "command": command, "runs": args.runs, "warmup": args.warmup, "timeout": args.timeout,
              "times_ms": times, **s, "machine": f"{platform.system()} {platform.machine()} {platform.node()}",
              "when": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(describe("baseline", s))
    print(f"saved: {path}")
    if s["spread_pct"] > conf["max_spread_pct"]:
        print(f"RESULT not verified: baseline saved, but the timings vary by {s['spread_pct']}% of the median (limit {conf['max_spread_pct']}%). A comparison against it cannot tell a change from noise. Quiet the machine or raise --runs, then take it again with --replace.")
        return 2
    print("RESULT pass: baseline saved")
    return 0


def cmd_compare(args, folder, conf):
    path = folder / f"{args.name}.json"
    if not path.exists():
        return blocked(f"no baseline named '{args.name}'. Take one BEFORE the change: measure.py baseline --name {args.name} -- <command>")
    base = json.loads(path.read_text(encoding="utf-8"))
    print(f"timing again: {' '.join(base['command'])}  ({base['warmup']} warm-up, {base['runs']} counted runs, as in the baseline)")
    times, problem = time_runs(base["command"], args.root, base["runs"], base["warmup"], base.get("timeout", args.timeout))
    if problem:
        return blocked(problem)
    b, c = {k: base[k] for k in ("median", "spread", "spread_pct", "min", "max")}, stats(times)
    floor = b["median"] * conf["relative_floor_pct"] / 100
    noise = round(max(b["spread"], c["spread"], floor), 2)
    diff = round(c["median"] - b["median"], 2)
    pct = round(diff / b["median"] * 100, 1) if b["median"] else 0.0
    print(describe("baseline", b) + f"  (taken {base['when']})")
    print(describe("now     ", c))
    print(f"difference: {diff:+} ms ({pct:+}%); noise: {noise} ms (wider spread of the two, at least {conf['relative_floor_pct']}% of the baseline median)")
    machine = f"{platform.system()} {platform.machine()} {platform.node()}"
    if base.get("machine") != machine:
        print("  note: the baseline was taken on a different machine; the two sets of times are not comparable")
    wide = max(b["spread_pct"], c["spread_pct"])
    if base.get("machine") != machine:
        state, text = "not verified", "the baseline comes from a different machine"
    elif abs(diff) <= noise and wide > conf["max_spread_pct"]:
        state, text = "not verified", f"the timings vary too much to tell: spread is {wide}% of the median (limit {conf['max_spread_pct']}%) and the difference of {diff:+} ms is inside it"
    elif abs(diff) <= noise:
        if args.goal == "not-slower":
            state, text = "pass", f"no change beyond noise ({diff:+} ms, noise {noise} ms)"
        else:
            state, text = "not verified", f"the difference of {diff:+} ms ({pct:+}%) is inside the noise of {noise} ms. This run is no evidence that the change helped."
    elif diff < 0:
        state, text = "pass", f"faster by {-diff} ms ({-pct}%), beyond the noise of {noise} ms. Keep the change."
    else:
        state, text = "fail", f"slower by {diff} ms ({pct}%), beyond the noise of {noise} ms. Revert the change."
    last = {"name": args.name, "goal": args.goal, "baseline": b, "now": {**c, "times_ms": times}, "difference_ms": diff,
            "difference_pct": pct, "noise_ms": noise, "state": state, "reason": text,
            "when": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
    (folder / f"{args.name}.last.json").write_text(json.dumps(last, indent=2) + "\n", encoding="utf-8")
    print(f"RESULT {state}: {text}")
    return {"pass": 0, "fail": 1}.get(state, 2)


def cmd_show(args, folder, conf):
    path = folder / f"{args.name}.json"
    if not path.exists():
        return blocked(f"no baseline named '{args.name}' in {folder}")
    print(path.read_text(encoding="utf-8").rstrip())
    return 0


def split_command(argv):
    """Everything after the first "--" is the command, kept exactly as given (it may hold its own "--")."""
    if "--" in argv:
        cut = argv.index("--")
        return argv[:cut], argv[cut + 1:]
    return argv, []


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path.cwd(), help="folder to run the command in and to keep .mstack/perf-check/ in (default: current folder)")
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("baseline", help="time a command and save the result")
    p.add_argument("--name", required=True, help="a short name for what is measured, such as build or import-users")
    p.add_argument("--runs", type=int, default=7, help="counted runs (default 7)")
    p.add_argument("--warmup", type=int, default=1, help="runs thrown away first (default 1)")
    p.add_argument("--timeout", type=int, default=600, help="seconds allowed per run (default 600)")
    p.add_argument("--replace", action="store_true", help="set an existing baseline aside and take a new one")
    p = sub.add_parser("compare", help="time the same command again and compare with the baseline")
    p.add_argument("--name", required=True)
    p.add_argument("--goal", choices=["faster", "not-slower"], default="faster", help="what the change was meant to do (default faster)")
    p.add_argument("--timeout", type=int, default=600)
    p = sub.add_parser("show", help="print a saved baseline")
    p.add_argument("--name", required=True)
    argv, command = split_command(sys.argv[1:])
    args = parser.parse_args(argv)
    args.command = command
    if not all(ch.isalnum() or ch in "-_." for ch in args.name) or args.name.startswith("."):
        return blocked("--name may hold letters, digits, '-', '_' and '.' only")
    args.root = args.root.resolve()
    conf, unverified = settings()
    if unverified and args.action != "show":
        print(f"note: noise settings ({', '.join(f'{k}={conf[k]}' for k in unverified)}) are unverified defaults from references/noise.json")
    return {"baseline": cmd_baseline, "compare": cmd_compare, "show": cmd_show}[args.action](args, args.root / ".mstack" / "perf-check", conf)


if __name__ == "__main__":
    sys.exit(main())

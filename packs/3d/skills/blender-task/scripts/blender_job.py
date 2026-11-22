#!/usr/bin/env python3
"""Run a Blender job without a window and prove the result from a state file.

  detect                      find Blender and print its version
  run --job <script.py> --state <new.json> [--blend <file.blend>] [-- <arguments for the job>]
                              run the job in background mode, then dump the scene's facts to the state file
  check --state <state.json> --facts <facts.json>
                              compare the state file with the facts taken from the user's request

How Blender is found, in this order: --blender <path>, the BLENDER_BIN environment variable, 'blender' on
PATH, then the usual application folders on macOS. Nothing is installed or downloaded.

run starts:  blender --background --factory-startup [file.blend] --python-exit-code 1 --python <job>
             --python assets/state_dump.py -- --mstack-state <state> <job arguments>
The job script is yours: it does the modelling and saves or exports to NEW files. This wrapper refuses to
write over an existing state file and fails if the opened .blend file changed on disk.

check reads facts like these (full format: references/facts-format.md):
  {"objects": [{"name": "Table", "type": "MESH", "dimensions_m": [1.2, 0.6, 0.75], "tolerance_m": 0.005,
                "polygons_max": 5000, "modifiers_none": true, "scale_applied": true}],
   "absent": ["Cube"], "count": {"MESH": 1}}
Every fact gets a row: ok, WRONG, or unknown when the state file lacks the value. No facts means nothing
was checked, and that is reported as not verified, never as a pass.

Exit codes: 0 = pass, 1 = fail, 2 = not verified or blocked (Blender not found, bad input).
"""
import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys

DUMP = pathlib.Path(__file__).resolve().parent.parent / "assets" / "state_dump.py"
MAC_APPS = ("/Applications/Blender.app/Contents/MacOS/Blender", "~/Applications/Blender.app/Contents/MacOS/Blender")
HOW_TO_GET = ("Blender was not found. Install it from blender.org (or your package manager), or pass --blender <path to the program>, "
              "or set BLENDER_BIN. This script installs nothing.")


def find_blender(explicit=None):
    """Return (path, version line) or (None, reason)."""
    candidates = []
    if explicit:
        candidates.append(explicit)
    else:
        if os.environ.get("BLENDER_BIN"):
            candidates.append(os.environ["BLENDER_BIN"])
        on_path = shutil.which("blender")
        if on_path:
            candidates.append(on_path)
        candidates.extend(str(pathlib.Path(p).expanduser()) for p in MAC_APPS)
        candidates.extend(str(p) for p in sorted(pathlib.Path("/Applications").glob("Blender*.app/Contents/MacOS/Blender")))
    for candidate in candidates:
        path = pathlib.Path(candidate)
        if not path.is_file() or not os.access(path, os.X_OK):
            continue
        try:
            out = subprocess.run([str(path), "--version"], capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            continue
        first = next((line.strip() for line in out.stdout.splitlines() if line.strip()), "")
        if "blender" in first.lower():
            return str(path), first
        return None, f"{path} runs but does not answer like Blender (first line of --version: '{first[:60]}')"
    if explicit:
        return None, f"no runnable program at {explicit}"
    return None, HOW_TO_GET


def file_hash(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def cmd_detect(args):
    path, detail = find_blender(args.blender)
    if not path:
        print(f"blocked: {detail}")
        return 2
    print(f"blender: {path}")
    print(f"version: {detail}")
    print("RESULT pass")
    return 0


def cmd_run(args):
    job, state = pathlib.Path(args.job), pathlib.Path(args.state)
    if not job.is_file():
        print(f"blocked: job script {job} does not exist")
        return 2
    if state.exists():
        print(f"blocked: {state} already exists; a state file is evidence and is never overwritten. Choose a new name.")
        return 2
    blend = pathlib.Path(args.blend) if args.blend else None
    if blend and not blend.is_file():
        print(f"blocked: {blend} does not exist")
        return 2
    exe, detail = find_blender(args.blender)
    if not exe:
        print(f"blocked: {detail}")
        return 2
    print(f"blender: {exe} ({detail})")
    state.parent.mkdir(parents=True, exist_ok=True)
    extra = [a for a in args.job_args if a != "--"]
    command = [exe, "--background", "--factory-startup"] + ([str(blend)] if blend else []) + [
        "--python-exit-code", "1", "--python", str(job), "--python", str(DUMP), "--", "--mstack-state", str(state), *extra]
    print("running: " + " ".join(command))
    before = file_hash(blend) if blend else None
    try:
        out = subprocess.run(command, capture_output=True, text=True, timeout=args.timeout)
    except subprocess.TimeoutExpired:
        print(f"RESULT not verified: Blender did not finish within {args.timeout} s")
        return 2
    except OSError as exc:
        print(f"blocked: Blender could not be started: {exc}")
        return 2
    tail = [line for line in (out.stdout + "\n" + out.stderr).splitlines() if line.strip()][-8:]
    if blend and file_hash(blend) != before:
        print(f"RESULT fail: the job changed {blend} on disk. Jobs save to a new file; restore the original from your copy or from git.")
        return 1
    if out.returncode != 0:
        print("\n".join("  | " + line for line in tail))
        print(f"RESULT fail: Blender exited with code {out.returncode}; the job script raised an error (last lines above)")
        return 1
    if not state.is_file() or state.stat().st_size == 0:
        print("\n".join("  | " + line for line in tail))
        print("RESULT fail: Blender exited with code 0 but wrote no state file, so nothing proves what the job did")
        return 1
    try:
        data = json.loads(state.read_text(encoding="utf-8"))
        objects = data["objects"]
    except (ValueError, KeyError, TypeError):
        print(f"RESULT fail: {state} is not a readable state file")
        return 1
    print(f"state: {state} ({data.get('blender_version', 'version not recorded')}, {len(objects)} objects)")
    for obj in objects[:40]:
        dims = " x ".join(f"{v:.3f}" for v in obj.get("dimensions", []))
        print(f"  {obj.get('name')!s:<24} {obj.get('type')!s:<8} {dims}  polygons {obj.get('polygons', '-')}")
    print("RESULT pass")
    return 0


def close(a, b, tolerance):
    return all(abs(x - y) <= tolerance for x, y in zip(a, b))


def check_object(fact, by_name, unit, rows):
    name = fact.get("name")
    obj = by_name.get(name)

    def row(what, expected, actual, state):
        rows.append({"fact": f"{name}: {what}", "expected": expected, "actual": actual, "state": state})

    if obj is None:
        row("exists", "present", "missing", "WRONG")
        return
    row("exists", "present", "present", "ok")
    if "type" in fact:
        row("type", fact["type"], obj.get("type"), "ok" if obj.get("type") == fact["type"] else "WRONG")
    if "dimensions_m" in fact:
        tolerance = fact.get("tolerance_m", 0.001)
        dims = obj.get("dimensions")
        if not isinstance(dims, list) or len(dims) != 3:
            row("dimensions", fact["dimensions_m"], "not in state file", "unknown")
        else:
            metres = [round(v * unit, 6) for v in dims]
            row(f"dimensions in metres (within {tolerance})", fact["dimensions_m"], metres,
                "ok" if close(metres, fact["dimensions_m"], tolerance) else "WRONG")
    polygons = obj.get("polygons_evaluated", obj.get("polygons"))
    for key, test in (("polygons_max", lambda v, limit: v <= limit), ("polygons_min", lambda v, limit: v >= limit)):
        if key in fact:
            if not isinstance(polygons, int):
                row(key, fact[key], "not in state file", "unknown")
            else:
                row(key + " (after modifiers)", fact[key], polygons, "ok" if test(polygons, fact[key]) else "WRONG")
    types = [m.get("type") for m in obj.get("modifiers", [])] if isinstance(obj.get("modifiers"), list) else None
    if "modifiers" in fact:
        if types is None:
            row("modifiers present", fact["modifiers"], "not in state file", "unknown")
        else:
            missing = [m for m in fact["modifiers"] if m not in types]
            row("modifiers present", fact["modifiers"], types, "WRONG" if missing else "ok")
    if fact.get("modifiers_none"):
        if types is None:
            row("no modifiers left", [], "not in state file", "unknown")
        else:
            row("no modifiers left (all applied or removed)", [], types, "ok" if not types else "WRONG")
    if "scale_applied" in fact:
        scale = obj.get("scale")
        if not isinstance(scale, list) or len(scale) != 3:
            row("scale applied", fact["scale_applied"], "not in state file", "unknown")
        else:
            applied = close(scale, [1.0, 1.0, 1.0], 1e-4)
            row("scale applied (scale is 1, 1, 1)", fact["scale_applied"], scale, "ok" if applied == bool(fact["scale_applied"]) else "WRONG")
    for key, field in (("materials_min", "materials"), ("uv_layers_min", "uv_layers")):
        if key in fact:
            value = obj.get(field)
            count = len(value) if isinstance(value, list) else value
            if not isinstance(count, int):
                row(key, fact[key], "not in state file", "unknown")
            else:
                row(key, fact[key], count, "ok" if count >= fact[key] else "WRONG")
    if "parent" in fact:
        row("parent", fact["parent"], obj.get("parent"), "ok" if obj.get("parent") == fact["parent"] else "WRONG")


def cmd_check(args):
    try:
        state = json.loads(pathlib.Path(args.state).read_text(encoding="utf-8"))
        facts = json.loads(pathlib.Path(args.facts).read_text(encoding="utf-8"))
        objects = state["objects"]
        by_name = {o["name"]: o for o in objects}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"RESULT not verified: cannot read the state or facts file: {exc}")
        return 2
    if not isinstance(facts, dict):
        print("RESULT not verified: the facts file is not a JSON object")
        return 2
    unit = state.get("unit_scale", 1.0) or 1.0
    rows = []
    for fact in facts.get("objects", []):
        check_object(fact, by_name, unit, rows)
    for name in facts.get("absent", []):
        rows.append({"fact": f"{name}: absent", "expected": "absent", "actual": "present" if name in by_name else "absent",
                     "state": "WRONG" if name in by_name else "ok"})
    for kind, wanted in facts.get("count", {}).items():
        found = sum(1 for o in objects if o.get("type") == kind)
        rows.append({"fact": f"count of {kind}", "expected": wanted, "actual": found, "state": "ok" if found == wanted else "WRONG"})
    if "unit_scale" in facts:
        rows.append({"fact": "scene unit scale", "expected": facts["unit_scale"], "actual": state.get("unit_scale"),
                     "state": "unknown" if "unit_scale" not in state else ("ok" if abs(state["unit_scale"] - facts["unit_scale"]) < 1e-9 else "WRONG")})
    print(f"state file: {args.state} ({state.get('blender_version', 'no Blender version recorded')}, {len(objects)} objects, unit scale {unit})")
    for r in rows:
        print(f"  {r['state']:<8} {r['fact']}: expected {r['expected']}, state file says {r['actual']}")
    if not rows:
        print("RESULT not verified: the facts file holds no facts, so nothing was checked. Write down what the request asked for.")
        return 2
    wrong = [r["fact"] for r in rows if r["state"] == "WRONG"]
    unknown = [r["fact"] for r in rows if r["state"] == "unknown"]
    if wrong:
        print(f"RESULT fail: {len(wrong)} of {len(rows)} facts do not hold: " + "; ".join(wrong))
        return 1
    if unknown:
        print("RESULT not verified: the state file lacks " + "; ".join(unknown))
        return 2
    print(f"{len(rows)} facts hold")
    print("RESULT pass")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--blender", help="path to the Blender program (default: search)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("detect", help="find Blender")
    run = sub.add_parser("run", help="run a job script and dump the scene state")
    run.add_argument("--job", required=True, help="your Blender Python script")
    run.add_argument("--state", required=True, help="NEW state file to write")
    run.add_argument("--blend", help=".blend file to open first (it is not changed)")
    run.add_argument("--timeout", type=int, default=900, help="seconds before giving up (default 900)")
    run.add_argument("job_args", nargs=argparse.REMAINDER, help="after --: arguments for the job script")
    check = sub.add_parser("check", help="compare a state file with facts")
    check.add_argument("--state", required=True)
    check.add_argument("--facts", required=True)
    args = parser.parse_args()
    return {"detect": cmd_detect, "run": cmd_run, "check": cmd_check}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Gate a glTF model (.glb or .gltf): is it a real file, sound in structure, inside a budget, and looked at?

  profiles                          list the budget profiles with their limits and whether each is verified
  inspect <file>                    what the file holds, plus structural errors
  check <file> --profile <name>     structure, budget, Khronos validator (when installed), render check; writes a manifest
  optimise <file> --out <new file> [--tool-args "..."]   run the gltf-transform optimiser (when installed) into a NEW file and compare
  compare --before a.png --after b.png   image difference of renders made before and after optimising

check options:
  --renders <png> ...      turntable screenshots of this model; without them the render check is not verified
  --waive key="reason"     accept one budget line that is over, with a written reason (kept in the manifest)
  --budgets <file>         another budgets file in the same format as references/budgets.json
  --project <folder>       where .mstack/gltf-gate/ manifests are written (default: the current folder)

Exit codes: 0 = pass, 1 = fail (the failing line is printed), 2 = not verified or blocked.
A missing tool never counts as a pass. The input file is never changed.
"""
import argparse
import datetime
import hashlib
import json
import pathlib
import platform
import shlex
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import glb  # noqa: E402
import pngstats  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
BUDGETS = HERE.parent / "references" / "budgets.json"
VALIDATOR_HELP = "Khronos glTF validator not found (looked for 'gltf_validator' on PATH). Get it from the KhronosGroup/glTF-Validator releases page."
OPTIMISER_HELP = "gltf-transform not found on PATH. It is the glTF Transform command-line tool (npm package @gltf-transform/cli); install it yourself, this script installs nothing."


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_budget_file(path):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8")), None
    except (OSError, ValueError) as exc:
        return None, f"budgets file {path} cannot be read: {exc}"


def tool_version(exe, flag="--version"):
    try:
        out = subprocess.run([exe, flag], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (out.stdout or out.stderr).strip().splitlines()
    return text[0][:80] if text else None


def stage(model, workdir):
    """Copy the model, and the files a .gltf refers to, into workdir so a tool can write beside the copy."""
    workdir.mkdir(parents=True, exist_ok=True)
    copy = workdir / model.path.name
    shutil.copy2(model.path, copy)
    if model.kind == "gltf":
        base = model.path.parent.resolve()
        for group in ("buffers", "images"):
            for entry in model.doc.get(group, []) or []:
                uri = entry.get("uri") if isinstance(entry, dict) else None
                if not isinstance(uri, str) or uri.startswith("data:") or "://" in uri:
                    continue
                source = (base / uri).resolve()
                if source.is_file() and (base == source or base in source.parents):
                    target = workdir / uri
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    return copy


def run_validator(model, workdir):
    """Run the Khronos validator on a copy and read its report. Returns a dict with a 'state'."""
    exe = shutil.which("gltf_validator")
    if not exe:
        return {"state": "missing", "detail": VALIDATOR_HELP}
    copy = stage(model, workdir)
    try:
        out = subprocess.run([exe, "-o", str(copy)], capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"state": "not verified", "detail": f"the validator did not finish: {exc}"}
    report = None
    start = out.stdout.find("{")
    if start != -1:
        try:
            report = json.loads(out.stdout[start:])
        except ValueError:
            report = None
    if report is None:
        for candidate in (copy.with_name(copy.name + ".report.json"), copy.with_suffix(".report.json")):
            if candidate.is_file():
                try:
                    report = json.loads(candidate.read_text(encoding="utf-8"))
                except ValueError:
                    report = None
                break
    issues = report.get("issues") if isinstance(report, dict) else None
    if not isinstance(issues, dict) or not isinstance(issues.get("numErrors"), int):
        return {"state": "not verified", "version": tool_version(exe),
                "detail": f"the validator ran (exit {out.returncode}) but gave no report with issues.numErrors"}
    messages = [m for m in issues.get("messages", []) if isinstance(m, dict)]
    return {"state": "fail" if issues["numErrors"] else "pass", "version": tool_version(exe),
            "errors": issues["numErrors"], "warnings": issues.get("numWarnings", 0),
            "messages": [{"severity": m.get("severity"), "code": m.get("code"), "pointer": m.get("pointer"),
                          "message": m.get("message")} for m in messages[:20]]}


def render_check(paths, min_views):
    """Pixel-check turntable screenshots. Returns a dict with a 'state'."""
    if not paths:
        return {"state": "not verified", "detail": "no renders given; make turntable screenshots in a browser and pass them with --renders"}
    try:
        limits, unverified = pngstats.load_thresholds(HERE.parent / "references" / "render_thresholds.json")
    except pngstats.Unreadable as exc:
        return {"state": "not verified", "detail": str(exc)}
    views, blank, unread = [], [], []
    for path in paths:
        try:
            stats = pngstats.measure(path)
        except pngstats.Unreadable as exc:
            unread.append(f"{path}: {exc}")
            continue
        stats["problems"] = pngstats.judge(stats, limits)
        views.append(stats)
        if stats["problems"]:
            blank.append(f"{path}: {stats['problems'][0]}")
    result = {"views": views, "unverified_limits": unverified}
    hashes = {}
    for stats in views:
        hashes.setdefault(stats["pixel_hash"], []).append(stats["file"])
    result["warnings"] = [f"same image from {len(v)} views ({', '.join(v)}); check that the camera moved" for v in hashes.values() if len(v) > 1]
    if blank:
        return {**result, "state": "fail", "detail": "; ".join(blank)}
    if unread:
        return {**result, "state": "not verified", "detail": "; ".join(unread)}
    if len(views) < min_views:
        return {**result, "state": "not verified", "detail": f"{len(views)} views given, a turntable needs {min_views}"}
    return {**result, "state": "pass", "detail": f"{len(views)} views hold a picture"}


def cmd_profiles(args):
    data, error = read_budget_file(args.budgets)
    if error:
        print(f"RESULT not verified: {error}")
        return 2
    for name, profile in data.get("profiles", {}).items():
        print(f"{name}")
        for key, entry in profile.items():
            mark = "verified" if entry.get("verified") else "UNVERIFIED"
            print(f"  {key:<18} {entry['value']:>9} {entry.get('unit', '')}  [{mark}, checked {entry.get('checked', '?')}, {entry.get('source', 'no source')}]")
    print("RESULT pass")
    return 0


def cmd_inspect(args):
    model = glb.load(args.file)
    glb.structure(model)
    if not model.readable:
        print(f"ERROR {model.errors[0]}")
        missing = model.kind == "missing"
        print(f"RESULT not verified: {model.errors[0]}" if missing else f"RESULT fail: {model.errors[0]}")
        return 2 if missing else 1
    summary = glb.stats(model)
    if args.json:
        print(json.dumps({"errors": model.errors, "warnings": model.warnings, "stats": summary}, indent=2))
    else:
        print("\n".join(glb.describe(summary)))
        for warning in model.warnings:
            print(f"warning         {warning}")
        for error in model.errors:
            print(f"ERROR           {error}")
    if model.errors:
        print(f"RESULT fail: {len(model.errors)} structural errors, first: {model.errors[0]}")
        return 1
    print("RESULT pass")
    return 0


def cmd_check(args):
    data, error = read_budget_file(args.budgets)
    if error:
        print(f"RESULT not verified: {error}")
        return 2
    profiles = data.get("profiles", {})
    if args.profile not in profiles:
        print(f"blocked: no budget profile '{args.profile}'. Choose one of: {', '.join(sorted(profiles))}")
        return 2
    waived = {}
    for item in args.waive:
        key, _, reason = item.partition("=")
        if key not in profiles[args.profile] or len(reason.strip()) < 10:
            print(f"blocked: --waive needs key=\"reason\" with a budget key of this profile and a reason of 10 characters or more; got '{item}'")
            return 2
        waived[key] = reason.strip()

    model = glb.load(args.file)
    if model.kind == "missing":
        print(f"RESULT not verified: {args.file}: no such file")
        return 2
    glb.structure(model)
    failures, unverified = [], []
    print("== structure")
    if not model.readable:
        print(f"ERROR {model.errors[0]}")
        print(f"RESULT fail: {model.errors[0]}")
        return 1
    summary = glb.stats(model)
    print("\n".join(glb.describe(summary)))
    for warning in model.warnings:
        print(f"warning         {warning}")
    for err in model.errors:
        print(f"ERROR           {err}")
    if model.errors:
        failures.append(f"{len(model.errors)} structural errors (first: {model.errors[0]})")

    print(f"== budget: {args.profile}")
    rows = glb.check_budget(summary, profiles[args.profile])
    for row in rows:
        state = row["state"]
        if state == "over" and row["key"] in waived:
            state = "waived"
        row["result"] = state
        measured = "unknown" if row["measured"] is None else row["measured"]
        print(f"  {row['key']:<18} {measured!s:>12} / {row['limit']:<9} {state.upper() if state != 'ok' else 'ok'}"
              + (f"  ({waived[row['key']]})" if state == "waived" else ""))
        if state == "over":
            failures.append(f"{row['key']} {measured} is over the {args.profile} budget of {row['limit']}")
        elif state == "unknown":
            unverified.append(f"budget line {row['key']} (could not be measured)")
    loose = sorted(r["key"] for r in rows if not r["verified"])
    if loose:
        print(f"  note: these limits are unverified working values, checked {data.get('checked', '?')}: {', '.join(loose)}")

    project = pathlib.Path(args.project).resolve()
    digest = sha256(model.path)
    out_dir = project / ".mstack" / "gltf-gate"
    print("== validator")
    validator = run_validator(model, out_dir / "work" / digest[:8])
    if validator["state"] == "missing":
        print(f"  not run: {validator['detail']}")
        unverified.append("Khronos validator not run (not installed)")
    elif validator["state"] == "not verified":
        print(f"  not verified: {validator['detail']}")
        unverified.append("Khronos validator gave no readable report")
    else:
        print(f"  {validator['errors']} errors, {validator['warnings']} warnings ({validator.get('version')})")
        for message in validator["messages"][:10]:
            print(f"    severity {message['severity']} {message['code']} {message['pointer']}: {message['message']}")
        if validator["state"] == "fail":
            failures.append(f"validator reports {validator['errors']} errors")

    print("== render")
    min_views = data.get("render", {}).get("min_views", {}).get("value", 4)
    render = render_check(args.renders, min_views)
    for view in render.get("views", []):
        verdict = "BLANK " + "; ".join(view["problems"]) if view["problems"] else "picture"
        print(f"  {view['file']}: {view['width']}x{view['height']} spread {view['spread']} dominant {view['dominant_share']:.1%} -> {verdict}")
    for warning in render.get("warnings", []):
        print(f"  warning: {warning}")
    print(f"  {render['state']}: {render['detail']}")
    if render["state"] == "fail":
        failures.append("render is blank: " + render["detail"])
    elif render["state"] != "pass":
        unverified.append("render check (" + render["detail"] + ")")
    else:
        print("  the pixels prove a picture exists, not that it is the right one: open the images and say what they show")

    result = "fail" if failures else ("not verified" if unverified else "pass")
    manifest = {
        "tool": "mstack gltf-gate", "made": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "file": str(model.path.resolve()), "sha256": digest, "profile": args.profile, "budgets_checked": data.get("checked"),
        "stats": summary, "structure_errors": model.errors, "budget": rows, "waived": waived, "validator": validator,
        "render": render, "tools": {"python": platform.python_version(), "gltf_validator": validator.get("version")},
        "result": result, "failures": failures, "not_verified": unverified,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{model.path.stem}-{digest[:8]}.json"
    target.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"manifest: {target}")
    if failures:
        print("RESULT fail: " + "; ".join(failures))
        return 1
    if unverified:
        print("RESULT not verified: " + "; ".join(unverified))
        return 2
    print("RESULT pass")
    return 0


def cmd_optimise(args):
    exe = shutil.which("gltf-transform")
    if not exe:
        print(f"blocked: {OPTIMISER_HELP}")
        return 2
    source, target = pathlib.Path(args.file), pathlib.Path(args.out)
    before = glb.load(source)
    glb.structure(before)
    if not before.readable or before.errors:
        print(f"RESULT fail: the input is not a sound model: {before.errors[0]}")
        return 1
    if target.exists():
        print(f"blocked: {target} already exists; this script never overwrites a file. Choose a new name.")
        return 2
    extra = shlex.split(args.tool_args or "")
    command = [exe, "optimize", str(source), str(target), *extra]
    print("running: " + " ".join(command))
    digest = sha256(source)
    try:
        out = subprocess.run(command, capture_output=True, text=True, timeout=1800)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"RESULT not verified: the optimiser did not finish: {exc}")
        return 2
    if sha256(source) != digest:
        print("RESULT fail: the optimiser changed the input file; restore it from your copy or from git")
        return 1
    if not target.is_file() or target.stat().st_size == 0:
        tail = (out.stderr or out.stdout).strip().splitlines()[-3:]
        print(f"RESULT fail: the optimiser (exit {out.returncode}) wrote no output file. " + " | ".join(tail))
        return 1
    after = glb.load(target)
    glb.structure(after)
    if not after.readable or after.errors:
        print(f"RESULT fail: the optimised file is not a sound model: {after.errors[0]}")
        return 1
    a, b = glb.stats(before), glb.stats(after)
    data, _ = read_budget_file(args.budgets)
    drift_limit = (data or {}).get("optimise", {}).get("max_bounds_drift_pct", {}).get("value", 1.0)
    problems = []
    print(f"{'':<18}{'before':>14}{'after':>14}")
    for key in ("file_size_bytes", "triangles_in_scene", "draw_calls_in_scene", "materials", "textures", "max_texture_px"):
        print(f"{key:<18}{a[key]!s:>14}{b[key]!s:>14}")
    if len(a["animations"]) != len(b["animations"]):
        problems.append(f"animations went from {len(a['animations'])} to {len(b['animations'])}")
    if a["bounds_m"] and b["bounds_m"]:
        for axis, (x, y) in zip("xyz", zip(a["bounds_m"]["size"], b["bounds_m"]["size"])):
            drift = abs(y - x) / x * 100 if x else (0.0 if y == 0 else 100.0)
            print(f"size {axis} (m)        {x:>14.4f}{y:>14.4f}  drift {drift:.2f}%")
            if drift > drift_limit:
                problems.append(f"size along {axis} changed by {drift:.2f}% (limit {drift_limit}%, an unverified working value)")
    elif a["bounds_m"]:
        problems.append("the optimised file has no readable bounding box")
    if b["triangles_in_scene"] > a["triangles_in_scene"]:
        problems.append("triangle count went up")
    if problems:
        print("RESULT fail: " + "; ".join(problems))
        return 1
    print(f"wrote {target}. Next: run 'check' on it, render both files from the same views and run 'compare'.")
    print("RESULT pass")
    return 0


def cmd_compare(args):
    if len(args.before) != len(args.after):
        print("blocked: give the same number of --before and --after images, in the same view order")
        return 2
    try:
        limits, unverified = pngstats.load_thresholds(HERE.parent / "references" / "render_thresholds.json")
    except pngstats.Unreadable as exc:
        print(f"RESULT not verified: {exc}")
        return 2
    damaged, unread = [], []
    for before, after in zip(args.before, args.after):
        try:
            diff = pngstats.difference(before, after)
        except pngstats.Unreadable as exc:
            unread.append(f"{before} vs {after}: {exc}")
            continue
        over = diff["mean_difference"] > limits["max_mean_difference"] or diff["changed_share"] > limits["max_changed_share"]
        print(f"{before} vs {after}: mean difference {diff['mean_difference']} of 255, changed pixels {diff['changed_share']:.2%} -> {'DIFFERENT' if over else 'same'}")
        if over:
            damaged.append(f"{after} differs from {before}")
    if unverified:
        print(f"limits are unverified working values: {', '.join(unverified)}")
    if damaged:
        print("RESULT fail: " + "; ".join(damaged))
        return 1
    if unread:
        print("RESULT not verified: " + "; ".join(unread))
        return 2
    print("RESULT pass")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--budgets", type=pathlib.Path, default=BUDGETS, help="budgets file (default: references/budgets.json)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("profiles", help="list budget profiles")
    inspect = sub.add_parser("inspect", help="report what a model holds")
    inspect.add_argument("file")
    inspect.add_argument("--json", action="store_true")
    check = sub.add_parser("check", help="run the whole gate and write a manifest")
    check.add_argument("file")
    check.add_argument("--profile", required=True, help="budget profile name (see 'profiles')")
    check.add_argument("--renders", nargs="*", default=[], help="turntable screenshots (PNG)")
    check.add_argument("--waive", action="append", default=[], metavar='KEY="REASON"', help="accept one over-budget line in writing")
    check.add_argument("--project", default=".", help="folder that gets .mstack/gltf-gate/ (default: current folder)")
    optimise = sub.add_parser("optimise", help="optimise into a new file and compare")
    optimise.add_argument("file")
    optimise.add_argument("--out", required=True, help="new file to write; never the input")
    optimise.add_argument("--tool-args", help='extra arguments for gltf-transform optimize, as one quoted string; read its own --help for the current flags')
    compare = sub.add_parser("compare", help="compare renders made before and after optimising")
    compare.add_argument("--before", nargs="+", required=True)
    compare.add_argument("--after", nargs="+", required=True)
    args = parser.parse_args()
    return {"profiles": cmd_profiles, "inspect": cmd_inspect, "check": cmd_check,
            "optimise": cmd_optimise, "compare": cmd_compare}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())

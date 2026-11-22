#!/usr/bin/env python3
"""Judge a capture report from a three.js or React Three Fiber page: did it render, and what does it cost?

  check_capture.py <report.json> [--profile desktop-web] [--refresh-hz 60] [--claims-frame-time]

The report is produced in the page by scripts/capture_snippet.js (format: references/capture-report.md).
This script fails the page when:
  - a pose has a blank or single-colour image. Screenshot files named in the report are decoded here and
    win over the numbers the page reported; a successful screenshot command proves nothing by itself
  - the page logged console errors
  - the renderer's counters after loading are over the budget profile
  - geometries or textures do not return to the starting count after the scene is disposed (a leak)
  - a frame time is claimed but the GPU adapter is a software renderer
It ends as not verified when something needed for a claim is missing: no poses, no adapter name with a
frame time, no counters, no dispose step.

Exit codes: 0 = pass, 1 = fail, 2 = not verified (or the report cannot be read).
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import pngstats  # noqa: E402

REFS = pathlib.Path(__file__).resolve().parent.parent / "references"
LEAK_KEYS = ("geometries", "textures")


def is_software(name, fragments):
    low = (name or "").lower()
    return next((f for f in fragments if f in low), None)


def check_pose(pose, base, limits):
    """Return (state, text, hash) for one pose entry."""
    name = pose.get("name", "?")
    shot = pose.get("screenshot")
    if shot:
        path = (base / shot) if not pathlib.Path(shot).is_absolute() else pathlib.Path(shot)
        if path.is_file():
            try:
                stats = pngstats.measure(path)
            except pngstats.Unreadable as exc:
                return "not verified", f"pose {name}: screenshot {shot} cannot be decoded ({exc})", None
            problems = pngstats.judge(stats, limits)
            text = f"pose {name}: {shot} {stats['width']}x{stats['height']} spread {stats['spread']} dominant {stats['dominant_share']:.1%} (decoded from the file)"
            return ("fail", text + " -> BLANK: " + "; ".join(problems), stats["pixel_hash"]) if problems else ("pass", text, stats["pixel_hash"])
    pixels = pose.get("pixels")
    needed = ("spread", "dominant_share", "transparent_share")
    if isinstance(pixels, dict) and all(isinstance(pixels.get(k), (int, float)) for k in needed):
        problems = pngstats.judge({**pixels, "dominant_colour": pixels.get("dominant_colour", "?")}, limits)
        text = f"pose {name}: spread {pixels['spread']} dominant {pixels['dominant_share']:.1%} (numbers reported by the page" \
               + (f"; screenshot {shot} not found" if shot else "") + ")"
        return ("fail", text + " -> BLANK: " + "; ".join(problems), pixels.get("pixel_hash")) if problems else ("pass", text, pixels.get("pixel_hash"))
    return "not verified", f"pose {name}: no readable screenshot and no pixel numbers", None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("report", type=pathlib.Path)
    parser.add_argument("--profile", default="desktop-web", help="counter budget profile in the budgets file")
    parser.add_argument("--budgets", type=pathlib.Path, default=REFS / "scene_budgets.json")
    parser.add_argument("--refresh-hz", type=float, help="judge the median frame time against 1000 / this rate")
    parser.add_argument("--claims-frame-time", action="store_true", help="the reply is going to state a frame time or frame rate")
    args = parser.parse_args()
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        budgets = json.loads(args.budgets.read_text(encoding="utf-8"))
        limits, loose = pngstats.load_thresholds(REFS / "render_thresholds.json")
    except (OSError, ValueError, pngstats.Unreadable) as exc:
        print(f"RESULT not verified: cannot read the report or the limits: {exc}")
        return 2
    if not isinstance(report, dict):
        print("RESULT not verified: the report is not a JSON object")
        return 2
    profile = budgets.get("profiles", {}).get(args.profile)
    if profile is None:
        print(f"blocked: no profile '{args.profile}'. Choose one of: {', '.join(sorted(budgets.get('profiles', {})))}")
        return 2
    failures, unverified = [], []

    print("== poses")
    poses = report.get("poses") if isinstance(report.get("poses"), list) else []
    seen = {}
    for pose in poses:
        state, text, digest = check_pose(pose if isinstance(pose, dict) else {}, args.report.parent, limits)
        print("  " + text)
        if state == "fail":
            failures.append(text.split(" -> ")[0].split(":")[0] + " is blank")
        elif state == "not verified":
            unverified.append(text)
        if digest:
            seen.setdefault(digest, []).append(pose.get("name", "?"))
    if not poses:
        print("  none in the report")
        unverified.append("no camera pose was captured")
    same = [names for names in seen.values() if len(names) > 1]
    for names in same:
        print(f"  warning: poses {', '.join(names)} gave the same image; check that the camera moved")
    if loose:
        print(f"  pixel limits are unverified working values: {', '.join(loose)}")

    print("== console")
    errors = report.get("console_errors")
    if not isinstance(errors, list):
        print("  not recorded")
        unverified.append("console errors were not recorded")
    elif errors:
        for line in errors[:10]:
            print(f"  error: {str(line)[:200]}")
        failures.append(f"{len(errors)} console errors")
    else:
        print("  clean")

    print("== GPU adapter and frame time")
    adapter = report.get("adapter") if isinstance(report.get("adapter"), dict) else {}
    name = adapter.get("renderer")
    frame = report.get("frame_time_ms") if isinstance(report.get("frame_time_ms"), dict) else None
    claimed = bool(frame) or args.claims_frame_time
    fragment = is_software(name, budgets.get("software_renderers", {}).get("value", []))
    print(f"  adapter: {name or 'not read'}" + (f"  <- software renderer (matches '{fragment}')" if fragment else ""))
    if frame:
        print(f"  frame time: median {frame.get('median')} ms, p95 {frame.get('p95')} ms over {frame.get('samples')} frames")
    if claimed and fragment:
        failures.append(f"frame time was measured on a software renderer ({name}); the number says nothing about a real GPU")
    elif claimed and not name:
        unverified.append("frame time: the GPU adapter name was not read, so the number cannot be trusted")
    elif claimed and not frame:
        unverified.append("frame time is to be claimed but the report holds none")
    elif not claimed:
        print("  frame time not measured; say so, do not estimate it")
    if frame and not fragment and name and args.refresh_hz:
        budget = 1000.0 / args.refresh_hz
        median = frame.get("median")
        if isinstance(median, (int, float)) and median > budget:
            failures.append(f"median frame time {median} ms is over the {budget:.2f} ms budget of {args.refresh_hz:g} Hz")

    print(f"== renderer counters, profile {args.profile}")
    counters = report.get("counters") if isinstance(report.get("counters"), dict) else {}
    loaded = counters.get("loaded") if isinstance(counters.get("loaded"), dict) else None
    if loaded is None:
        print("  no 'loaded' counters in the report")
        unverified.append("renderer counters were not captured")
    else:
        for key, entry in profile.items():
            value = loaded.get(key)
            if not isinstance(value, (int, float)):
                print(f"  {key:<11} not reported")
                unverified.append(f"counter {key} was not reported")
                continue
            over = value > entry["value"]
            print(f"  {key:<11} {value:>10} / {entry['value']:<10} {'OVER' if over else 'ok'}")
            if over:
                failures.append(f"{key} {value} is over the {args.profile} budget of {entry['value']}")
        print(f"  budget numbers are unverified working values, checked {budgets.get('checked', '?')}")

    print("== leak check")
    before = counters.get("before") if isinstance(counters.get("before"), dict) else None
    after = counters.get("after_dispose") if isinstance(counters.get("after_dispose"), dict) else None
    if before is None or after is None:
        print("  not run: the report needs counters 'before' loading and 'after_dispose'")
        unverified.append("leak check (no before and after_dispose counters)")
    else:
        for key in LEAK_KEYS:
            a, b = before.get(key), after.get(key)
            if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
                unverified.append(f"leak check: {key} not reported")
                continue
            print(f"  {key:<11} before {a}, after dispose {b} -> {'LEAK' if b > a else 'ok'}")
            if b > a:
                failures.append(f"{b - a} {key} are still in memory after the scene was disposed")
        a, b = before.get("programs"), after.get("programs")
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and b > a:
            print(f"  warning: {b - a} shader programs stayed after dispose (programs can be cached; check if it grows on each load)")

    if failures:
        print("RESULT fail: " + "; ".join(failures))
        return 1
    if unverified:
        print("RESULT not verified: " + "; ".join(unverified))
        return 2
    print("RESULT pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())

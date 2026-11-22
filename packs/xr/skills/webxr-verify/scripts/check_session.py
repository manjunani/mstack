#!/usr/bin/env python3
"""Judge the report of an emulated WebXR session: did a session start, and did every pose and input render?

  check_session.py <report.json> [--poses front,left,right,up,down] [--inputs controllers,hands]

The report is written in the page by scripts/session_snippet.js while a WebXR emulator stands in for the
headset (format in references/session-report.md). This script fails the run when:
  - no session started, or the mode is not the one asked for
  - a required head pose or input mode has no capture, or its image is blank or one colour
    (screenshot files named in the report are decoded here and win over the page's own numbers)
  - console errors were logged
  - draw calls or triangles are over the limits in references/session_limits.json
It ends as not verified when the GPU adapter name is missing, and it never accepts a frame rate from an
emulator. Whatever the result, it prints what an emulator cannot prove.

Exit codes: 0 = pass, 1 = fail, 2 = not verified (or the report cannot be read).
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import pngstats  # noqa: E402

REFS = pathlib.Path(__file__).resolve().parent.parent / "references"
CANNOT = [
    "real frame rate and frame timing on the headset (an emulator runs on the desktop GPU, or on a software one)",
    "comfort: motion sickness, vergence, how heavy the scene feels; run xr-comfort-review for distances and sizes, then try it on a person",
    "tracking: drift, occlusion of hands or controllers, lighting, the real room",
    "the headset browser itself: its WebXR version, permissions prompts, and memory limits",
]


def judge_capture(entry, base, limits):
    shot = entry.get("screenshot")
    label = f"{entry.get('kind', 'pose')} {entry.get('name', '?')}"
    if shot:
        path = pathlib.Path(shot) if pathlib.Path(shot).is_absolute() else base / shot
        if path.is_file():
            try:
                stats = pngstats.measure(path)
            except pngstats.Unreadable as exc:
                return "not verified", f"{label}: {shot} cannot be decoded ({exc})"
            problems = pngstats.judge(stats, limits)
            text = f"{label}: {shot} spread {stats['spread']} dominant {stats['dominant_share']:.1%} (decoded from the file)"
            return ("fail", text + " -> BLANK: " + "; ".join(problems)) if problems else ("pass", text)
    pixels = entry.get("pixels")
    if isinstance(pixels, dict) and all(isinstance(pixels.get(k), (int, float)) for k in ("spread", "dominant_share", "transparent_share")):
        problems = pngstats.judge({**pixels, "dominant_colour": pixels.get("dominant_colour", "?")}, limits)
        text = f"{label}: spread {pixels['spread']} dominant {pixels['dominant_share']:.1%} (numbers from the page)"
        return ("fail", text + " -> BLANK: " + "; ".join(problems)) if problems else ("pass", text)
    return "not verified", f"{label}: no readable screenshot and no pixel numbers"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("report", type=pathlib.Path)
    parser.add_argument("--mode", choices=["immersive-vr", "immersive-ar"], default="immersive-vr")
    parser.add_argument("--poses", default="front,left,right", help="head poses that must be captured (comma separated)")
    parser.add_argument("--inputs", default="controllers,hands", help="input modes that must be captured; empty string for none")
    args = parser.parse_args()
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        limits, loose = pngstats.load_thresholds(REFS / "render_thresholds.json")
        session_limits = json.loads((REFS / "session_limits.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, pngstats.Unreadable) as exc:
        print(f"RESULT not verified: cannot read the report or the limits: {exc}")
        return 2
    if not isinstance(report, dict):
        print("RESULT not verified: the report is not a JSON object")
        return 2
    failures, unverified = [], []
    session = report.get("session") if isinstance(report.get("session"), dict) else {}
    print("== session")
    if not session.get("started"):
        failures.append("no XR session started" + (f" ({session.get('error')})" if session.get("error") else ""))
        print(f"  not started: {session.get('error', 'no reason recorded')}")
    else:
        print(f"  started: mode {session.get('mode')}, emulator {report.get('emulator', 'not named')}")
        if session.get("mode") != args.mode:
            failures.append(f"session mode is {session.get('mode')}, expected {args.mode}")
        if session.get("ended") is False:
            print("  warning: the session was not ended at the end of the run; the exit path is untested")
    print("== captures")
    captures = [c for c in report.get("captures", []) if isinstance(c, dict)] if isinstance(report.get("captures"), list) else []
    for entry in captures:
        state, text = judge_capture(entry, args.report.parent, limits)
        print("  " + text)
        if state == "fail":
            failures.append(f"{entry.get('kind', 'pose')} {entry.get('name')} is blank")
        elif state == "not verified":
            unverified.append(text)
    for kind, wanted in (("pose", args.poses), ("input", args.inputs)):
        names = [n.strip() for n in wanted.split(",") if n.strip()]
        have = {c.get("name") for c in captures if c.get("kind", "pose") == kind}
        missing = [n for n in names if n not in have]
        if missing:
            failures.append(f"no capture for {kind} {', '.join(missing)}")
    if loose:
        print(f"  pixel limits are unverified working values: {', '.join(loose)}")
    print("== console")
    errors = report.get("console_errors")
    if not isinstance(errors, list):
        unverified.append("console errors were not recorded")
        print("  not recorded")
    elif errors:
        for line in errors[:8]:
            print(f"  error: {str(line)[:200]}")
        failures.append(f"{len(errors)} console errors")
    else:
        print("  clean")
    print("== cost")
    counters = report.get("counters") if isinstance(report.get("counters"), dict) else {}
    for key, limit_key in (("calls", "max_draw_calls"), ("triangles", "max_triangles")):
        value, limit = counters.get(key), session_limits["limits"][limit_key]["value"]
        if not isinstance(value, (int, float)):
            unverified.append(f"{key} not reported")
            print(f"  {key}: not reported")
            continue
        print(f"  {key}: {value} / {limit} {'OVER' if value > limit else 'ok'} (unverified working limit)")
        if value > limit:
            failures.append(f"{key} {value} is over {limit}")
    adapter = (report.get("adapter") or {}).get("renderer") if isinstance(report.get("adapter"), dict) else None
    soft = next((f for f in session_limits["software_renderers"]["value"] if f in (adapter or "").lower()), None)
    print(f"  GPU adapter: {adapter or 'not read'}" + ("  <- software renderer" if soft else ""))
    if not adapter:
        unverified.append("GPU adapter name not read")
    if report.get("frame_time_ms"):
        print("  a frame time is in the report; it is NOT accepted: an emulator says nothing about headset frame rate")
    print("what an emulator cannot prove (needs a headset and a person):")
    for line in CANNOT:
        print(f"  - {line}")
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

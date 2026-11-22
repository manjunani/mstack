#!/usr/bin/env python3
"""Measure every UI element of a running XR scene against comfort and readability limits.

  comfort.py <scene_dump.json> [--json] [--thresholds file]

The dump is made in the running page by scripts/scene_dump.js (three.js), never typed by hand:
  {"head": {"position": [x, y, z], "forward": [x, y, z]},
   "elements": [{"name": "menu", "position": [x, y, z], "size": [w, h], "text_height": 0.02,
                 "head_locked": false, "interactive": true}]}
Positions are world metres. "forward" is the head's looking direction; it is normalised here.

For each element it computes:
  distance      metres from the head to the element's centre
  text angle    visual angle of one line of text (from text_height at that distance), when the element has text
  offset        angle between the forward direction and the element's centre
  target angle  visual angle of the smaller side, for interactive elements
and gives each check ok, FAIL or skipped (with the reason a value was missing). Nothing missing is ever
counted as ok. Limits come from references/comfort_thresholds.json; all of them are unverified working values.

Exit codes: 0 = every measured check passes, 1 = at least one fails, 2 = not verified (bad dump, or
nothing could be measured).
"""
import argparse
import json
import math
import pathlib
import sys

THRESHOLDS = pathlib.Path(__file__).resolve().parent.parent / "references" / "comfort_thresholds.json"


def vec(value):
    if isinstance(value, list) and len(value) == 3 and all(isinstance(v, (int, float)) for v in value):
        return [float(v) for v in value]
    return None


def angle_of(size, distance):
    return math.degrees(2 * math.atan(size / (2 * distance)))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dump", type=pathlib.Path)
    parser.add_argument("--thresholds", type=pathlib.Path, default=THRESHOLDS)
    parser.add_argument("--json", action="store_true", help="print the rows as JSON")
    args = parser.parse_args()
    try:
        dump = json.loads(args.dump.read_text(encoding="utf-8"))
        data = json.loads(args.thresholds.read_text(encoding="utf-8"))
        limits = {k: v["value"] for k, v in data["thresholds"].items()}
    except (OSError, ValueError, KeyError) as exc:
        print(f"RESULT not verified: cannot read the dump or the limits: {exc}")
        return 2
    head = dump.get("head") if isinstance(dump, dict) else None
    origin = vec(head.get("position")) if isinstance(head, dict) else None
    forward = vec(head.get("forward")) if isinstance(head, dict) else None
    if not origin or not forward or not any(forward):
        print("RESULT not verified: the dump has no head position and forward direction")
        return 2
    length = math.sqrt(sum(v * v for v in forward))
    forward = [v / length for v in forward]
    elements = dump.get("elements") if isinstance(dump.get("elements"), list) else []
    if not elements:
        print("RESULT not verified: the dump lists no UI elements, so nothing was measured")
        return 2
    rows, failures, measured = [], [], 0
    for index, element in enumerate(elements):
        name = str(element.get("name") or f"element {index}") if isinstance(element, dict) else f"element {index}"
        row = {"name": name, "checks": []}
        rows.append(row)

        def check(label, value, ok, limit_text):
            nonlocal measured
            measured += 1
            row["checks"].append({"check": label, "value": round(value, 3), "state": "ok" if ok else "FAIL", "limit": limit_text})
            if not ok:
                failures.append(f"{name}: {label} {value:.2f} ({limit_text})")

        def skip(label, why):
            row["checks"].append({"check": label, "value": None, "state": "skipped", "limit": why})

        position = vec(element.get("position")) if isinstance(element, dict) else None
        if not position:
            skip("all", "no world position in the dump")
            continue
        to = [p - o for p, o in zip(position, origin)]
        distance = math.sqrt(sum(v * v for v in to))
        if distance < 1e-6:
            skip("all", "element sits at the head position")
            continue
        check("distance m", distance, limits["min_distance_m"] <= distance <= limits["max_distance_m"],
              f"{limits['min_distance_m']} to {limits['max_distance_m']} m")
        cosine = max(-1.0, min(1.0, sum(a * b for a, b in zip(to, forward)) / distance))
        offset = math.degrees(math.acos(cosine))
        locked = bool(element.get("head_locked"))
        limit = limits["max_head_locked_offset_deg"] if locked else limits["max_offset_deg"]
        check("offset from forward deg" + (" (head-locked)" if locked else ""), offset, offset <= limit, f"at most {limit} deg")
        text = element.get("text_height")
        if isinstance(text, (int, float)) and text > 0:
            value = angle_of(text, distance)
            check("text angle deg", value, value >= limits["min_text_angle_deg"], f"at least {limits['min_text_angle_deg']} deg")
        elif element.get("has_text"):
            skip("text angle deg", "element has text but the dump gives no text_height")
        if element.get("interactive"):
            size = element.get("size")
            if isinstance(size, list) and len(size) >= 2 and all(isinstance(v, (int, float)) and v > 0 for v in size[:2]):
                value = angle_of(min(size[:2]), distance)
                check("target angle deg", value, value >= limits["min_target_angle_deg"], f"at least {limits['min_target_angle_deg']} deg")
            else:
                skip("target angle deg", "interactive element without a size")
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for row in rows:
            print(row["name"])
            for c in row["checks"]:
                value = "-" if c["value"] is None else f"{c['value']:.2f}"
                print(f"  {c['state']:<8} {c['check']:<34} {value:>8}   {c['limit']}")
    skipped = sum(1 for r in rows for c in r["checks"] if c["state"] == "skipped")
    print(f"{len(rows)} elements, {measured} checks measured, {len(failures)} failed, {skipped} skipped")
    print(f"all limits are unverified working values (checked {data.get('checked', '?')}); re-source them before treating a fail as final")
    print("not measured here: locomotion speed and turning, frame rate, flicker, how the scene feels; those need the app's settings and a person in a headset")
    if failures:
        print("RESULT fail: " + "; ".join(failures))
        return 1
    if measured == 0:
        print("RESULT not verified: no element had the values needed for a check")
        return 2
    if skipped:
        print(f"RESULT not verified: {skipped} checks skipped for missing values (listed above); the measured ones pass")
        return 2
    print("RESULT pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())

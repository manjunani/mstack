#!/usr/bin/env python3
"""Check a rigged or animated glTF model by numbers, before anyone trusts a preview.

  list <file>                     skins, bones with their parents, clips with length and what they move
  check <file> --joint <name>     follow one foot or hand bone through every clip and judge contact

check works by forward kinematics: for each sample time it evaluates the animated translation, rotation and
scale of the bone and of every parent above it, and takes the world position of the bone's origin. From that:
  height     distance of the bone above the floor along the up axis
  contact    samples where the height is within the contact limit
  below      samples where the bone is under the floor by more than the limit (fail)
  sliding    sideways travel while the bone stays in contact (fail over the limit, unless --in-place)
  scale      change of the bone's world scale against the rest pose (fail over the limit)
  skeleton   growth of the box around all bone origins against the rest pose (reported, warned, never a fail)

options for check:
  --clip <name or number>   one clip only (default: every clip)
  --up y|z                  up axis (default y, which is what glTF uses)
  --floor <metres>          floor height. Default: the bone's own rest-pose height, which assumes the rest pose stands on the floor
  --fps <n>                 extra evenly spaced samples between keyframes (default 30; 0 = keyframes only)
  --in-place                the clip is meant to stay on the spot (treadmill); sliding is reported but not judged
  --all                     print every sample row, not only the notable ones

What this script does NOT compute, and says so in its output: the skinned mesh surface. Whether the sole of
the shoe cuts the floor, whether the mesh stretches, and the true mesh bounds per frame need every vertex
blended by its weights, which this script does not do. Limits are in references/motion_thresholds.json.

Exit codes: 0 = pass, 1 = fail, 2 = not verified or blocked (no such bone, no contact found, unreadable file).
"""
import argparse
import bisect
import json
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import glb  # noqa: E402

THRESHOLDS = pathlib.Path(__file__).resolve().parent.parent / "references" / "motion_thresholds.json"
LIMB_WORDS = ("foot", "toe", "ankle", "heel", "hand", "wrist", "palm")
NOT_COMPUTED = [
    "the skinned mesh surface: this follows bone origins only, so a sole or fingertip can still cut the floor",
    "mesh bounds per frame and mesh stretching: both need every vertex blended by its skin weights",
    "whether the pose looks right: twisted limbs and wrong facing need a rendered view",
]


def load_thresholds(path):
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    values = {name: entry["value"] for name, entry in data["thresholds"].items()}
    loose = [name for name, entry in data["thresholds"].items() if not entry.get("verified")]
    for name in ("contact_height_m", "below_floor_m", "max_slide_m", "max_scale_drift_pct", "skeleton_growth_warn_pct"):
        if name not in values:
            raise KeyError(name)
    return values, loose


def node_name(nodes, index):
    return nodes[index].get("name") or f"node {index}"


def parents_of(nodes):
    parent = {}
    for index, node in enumerate(nodes):
        for child in node.get("children", []) or []:
            parent[child] = index
    return parent


def slerp(a, b, t):
    dot = sum(x * y for x, y in zip(a, b))
    if dot < 0:
        b, dot = [-v for v in b], -dot
    if dot > 0.9995:
        out = [x + (y - x) * t for x, y in zip(a, b)]
    else:
        angle = math.acos(max(-1.0, min(1.0, dot)))
        sa = math.sin(angle)
        wa, wb = math.sin((1 - t) * angle) / sa, math.sin(t * angle) / sa
        out = [x * wa + y * wb for x, y in zip(a, b)]
    length = math.sqrt(sum(v * v for v in out)) or 1.0
    return [v / length for v in out]


class Channel:
    def __init__(self, times, values, mode, path):
        self.times, self.mode, self.path = times, mode, path
        if mode == "CUBICSPLINE":
            self.tan_in, self.values, self.tan_out = values[0::3], values[1::3], values[2::3]
        else:
            self.values = values

    def at(self, t):
        times, values = self.times, self.values
        if t <= times[0]:
            return list(values[0])
        if t >= times[-1]:
            return list(values[-1])
        k = bisect.bisect_right(times, t) - 1
        span = times[k + 1] - times[k]
        u = (t - times[k]) / span if span > 0 else 0.0
        if self.mode == "STEP":
            return list(values[k])
        if self.mode == "CUBICSPLINE":
            u2, u3 = u * u, u * u * u
            out = [(2 * u3 - 3 * u2 + 1) * p0 + (u3 - 2 * u2 + u) * span * m0 + (-2 * u3 + 3 * u2) * p1 + (u3 - u2) * span * m1
                   for p0, m0, p1, m1 in zip(values[k], self.tan_out[k], values[k + 1], self.tan_in[k + 1])]
            if self.path == "rotation":
                length = math.sqrt(sum(v * v for v in out)) or 1.0
                out = [v / length for v in out]
            return out
        if self.path == "rotation":
            return slerp(values[k], values[k + 1], u)
        return [x + (y - x) * u for x, y in zip(values[k], values[k + 1])]


def read_clip(model, anim):
    """Return ({node: {path: Channel}}, list of problems) for one animation."""
    channels, problems = {}, []
    samplers = anim.get("samplers", [])
    for number, channel in enumerate(anim.get("channels", [])):
        target = channel.get("target", {})
        node, path = target.get("node"), target.get("path")
        if node is None or path not in ("translation", "rotation", "scale"):
            continue
        sampler = samplers[channel["sampler"]]
        try:
            times = glb.read_accessor(model, sampler["input"])
            values = glb.read_accessor(model, sampler["output"])
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            problems.append(f"channel {number} ({path}) cannot be read: {exc}")
            continue
        mode = sampler.get("interpolation", "LINEAR")
        expected = len(times) * (3 if mode == "CUBICSPLINE" else 1)
        if len(values) != expected or not times:
            problems.append(f"channel {number} ({path}): {len(times)} key times but {len(values)} values")
            continue
        if any(b < a for a, b in zip(times, times[1:])):
            problems.append(f"channel {number} ({path}): key times go backwards")
            continue
        channels.setdefault(node, {})[path] = Channel(times, values, mode, path)
    return channels, problems


def local_matrix(node, animated, t):
    if not animated and isinstance(node.get("matrix"), list):
        return glb.node_matrix(node)
    translation, rotation, scale = glb.node_trs(node)
    if animated:
        if "translation" in animated:
            translation = animated["translation"].at(t)
        if "rotation" in animated:
            rotation = animated["rotation"].at(t)
        if "scale" in animated:
            scale = animated["scale"].at(t)
    return glb.trs_matrix(translation, rotation, scale)


def world_matrix(nodes, parent, index, channels, t):
    chain = []
    while index is not None:
        chain.append(index)
        index = parent.get(index)
    matrix = glb.IDENTITY
    for node in reversed(chain):
        matrix = glb.mat_mul(matrix, local_matrix(nodes[node], channels.get(node) if channels else None, t))
    return matrix


def scale_of(matrix):
    return [math.sqrt(sum(matrix[c * 4 + r] ** 2 for r in range(3))) for c in range(3)]


def box_diagonal(points):
    return math.sqrt(sum((max(p[a] for p in points) - min(p[a] for p in points)) ** 2 for a in range(3)))


def find_joint(nodes, joints, wanted):
    """Return (index, None) or (None, message)."""
    pool = joints or list(range(len(nodes)))
    exact = [i for i in pool if nodes[i].get("name") == wanted]
    if len(exact) == 1:
        return exact[0], None
    partial = exact or [i for i in pool if wanted.lower() in (nodes[i].get("name") or "").lower()]
    if len(partial) == 1:
        return partial[0], None
    if not partial:
        limbs = [node_name(nodes, i) for i in pool if any(w in (nodes[i].get("name") or "").lower() for w in LIMB_WORDS)]
        hint = f" Bones that look like feet or hands: {', '.join(limbs[:12])}." if limbs else " Run 'list' to see every bone."
        return None, f"no bone named '{wanted}'.{hint}"
    return None, f"'{wanted}' matches {len(partial)} bones: {', '.join(node_name(nodes, i) for i in partial[:12])}. Give the exact name."


def open_model(path):
    model = glb.load(path)
    glb.structure(model)
    if not model.readable:
        return None, f"RESULT not verified: {model.errors[0]}"
    if model.errors:
        for error in model.errors[:10]:
            print(f"ERROR {error}")
        return None, f"RESULT fail: the file has {len(model.errors)} structural errors; fix those first"
    return model, None


def cmd_list(args):
    model, problem = open_model(args.file)
    if problem:
        print(problem)
        return 1 if problem.startswith("RESULT fail") else 2
    doc = model.doc
    nodes, parent = doc.get("nodes", []), parents_of(doc.get("nodes", []))
    skins, anims = doc.get("skins", []), doc.get("animations", [])
    for s, skin in enumerate(skins):
        print(f"skin {s} '{skin.get('name', '')}': {len(skin['joints'])} bones")
        for joint in skin["joints"]:
            depth, up = 0, parent.get(joint)
            while up is not None and up in skin["joints"]:
                depth, up = depth + 1, parent.get(up)
            mark = "  <- foot or hand?" if any(w in (nodes[joint].get("name") or "").lower() for w in LIMB_WORDS) else ""
            print(f"  {'  ' * depth}{node_name(nodes, joint)}{mark}")
    if not skins:
        print("no skin: this model has no bones")
    for a, anim in enumerate(anims):
        channels, problems = read_clip(model, anim)
        length = max((c.times[-1] for paths in channels.values() for c in paths.values()), default=0.0)
        modes = sorted({c.mode for paths in channels.values() for c in paths.values()})
        print(f"clip {a} '{anim.get('name', '')}': {length:.3f} s, moves {len(channels)} nodes, interpolation {', '.join(modes) or 'none'}")
        for line in problems:
            print(f"  problem: {line}")
    if not anims:
        print("no animation clips")
    if not skins and not anims:
        print("RESULT not verified: nothing to check, the model has no skin and no animation")
        return 2
    print("RESULT pass")
    return 0


def judge_clip(model, anim, joint, args, limits, all_joints):
    """Return (state, lines, record) for one clip. state is pass, fail or not verified."""
    nodes = model.doc["nodes"]
    parent = parents_of(nodes)
    axis = "xyz".index(args.up)
    side = [a for a in range(3) if a != axis]
    channels, problems = read_clip(model, anim)
    lines = [f"  problem: {p}" for p in problems]
    chain, up = [], joint
    while up is not None:
        chain.append(up)
        up = parent.get(up)
    moving = [n for n in chain if n in channels]
    rest = world_matrix(nodes, parent, joint, None, 0.0)
    rest_height = rest[12 + axis]
    floor = rest_height if args.floor is None else args.floor
    record = {"clip": anim.get("name", ""), "joint": node_name(nodes, joint), "floor_m": floor, "samples": []}
    if not moving:
        lines.append("  this clip does not move the bone or any of its parents")
        return "not verified", lines, record
    times = sorted({t for n in moving for c in channels[n].values() for t in c.times})
    end = times[-1]
    if args.fps > 0 and end > 0:
        steps = min(int(end * args.fps), 5000)
        times = sorted(set(times) | {round(end * k / steps, 6) for k in range(steps + 1)} if steps else set(times))
    rest_scale = scale_of(rest)
    rows, below, worst_slide, run, drift = [], [], 0.0, 0.0, 0.0
    previous = None
    for t in times:
        matrix = world_matrix(nodes, parent, joint, channels, t)
        pos = matrix[12:15]
        height = pos[axis] - floor
        state = "below" if height < -limits["below_floor_m"] else ("contact" if height <= limits["contact_height_m"] else "air")
        step = 0.0
        if previous and previous["state"] != "air" and state != "air":
            step = math.hypot(pos[side[0]] - previous["pos"][side[0]], pos[side[1]] - previous["pos"][side[1]])
            run += step
        else:
            run = 0.0
        worst_slide = max(worst_slide, run)
        scale = scale_of(matrix)
        drift = max(drift, max(abs(s - r) / r * 100 if r else 0.0 for s, r in zip(scale, rest_scale)))
        row = {"t": round(t, 4), "pos": [round(v, 5) for v in pos], "height": round(height, 5), "state": state,
               "slide_run": round(run, 5)}
        rows.append(row)
        if state == "below":
            below.append(row)
        previous = row
    record["samples"] = rows
    contacts = [r for r in rows if r["state"] != "air"]

    growth = None
    if all_joints:
        rest_points = [world_matrix(nodes, parent, j, None, 0.0)[12:15] for j in all_joints]
        rest_diag = box_diagonal(rest_points)
        picks = times[::max(1, len(times) // 60)]
        if rest_diag > 0:
            growth = max(box_diagonal([world_matrix(nodes, parent, j, channels, t)[12:15] for j in all_joints]) / rest_diag * 100 - 100
                         for t in picks)

    shown = rows if args.all or len(rows) <= 24 else [
        r for i, r in enumerate(rows)
        if i in (0, len(rows) - 1) or r["state"] == "below" or r["state"] != rows[i - 1]["state"] or r["slide_run"] >= worst_slide > 0]
    lines.append(f"  {'time s':>8} {'x':>9} {'y':>9} {'z':>9} {'height':>9}  state    slide run")
    for r in shown:
        lines.append(f"  {r['t']:>8.3f} {r['pos'][0]:>9.4f} {r['pos'][1]:>9.4f} {r['pos'][2]:>9.4f} {r['height']:>9.4f}  {r['state']:<8} {r['slide_run']:.4f}")
    if len(shown) < len(rows):
        lines.append(f"  ({len(rows) - len(shown)} unremarkable samples not shown; --all prints them)")
    lowest = min(r["height"] for r in rows)
    record.update({"lowest_height_m": lowest, "worst_slide_m": round(worst_slide, 5), "scale_drift_pct": round(drift, 3),
                   "skeleton_growth_pct": None if growth is None else round(growth, 2), "contact_samples": len(contacts)})
    lines.append(f"  lowest height {lowest:.4f} m; contact in {len(contacts)} of {len(rows)} samples; worst slide in one contact {worst_slide:.4f} m; scale drift {drift:.2f}%")
    if growth is not None:
        lines.append(f"  box around all bone origins grows by at most {growth:.1f}% over the rest pose")
        if growth > limits["skeleton_growth_warn_pct"]:
            lines.append(f"  warning: that is over {limits['skeleton_growth_warn_pct']}%; a bone may be flying away from the body")
    if any(c.mode == "CUBICSPLINE" for n in moving for c in channels[n].values()):
        lines.append("  note: cubic spline channels were evaluated with the stored tangents")

    failures = []
    if below:
        failures.append(f"bone is {-min(r['height'] for r in below):.4f} m under the floor at t={below[0]['t']} s (limit {limits['below_floor_m']} m)")
    if worst_slide > limits["max_slide_m"]:
        if args.in_place:
            lines.append(f"  sliding {worst_slide:.4f} m not judged: --in-place was given")
        else:
            failures.append(f"bone slides {worst_slide:.4f} m while in contact (limit {limits['max_slide_m']} m)")
    if drift > limits["max_scale_drift_pct"]:
        failures.append(f"bone scale drifts {drift:.2f}% from the rest pose (limit {limits['max_scale_drift_pct']}%)")
    if failures:
        lines.extend(f"  FAIL {f}" for f in failures)
        record["failures"] = failures
        return "fail", lines, record
    if problems:
        return "not verified", lines, record
    if not contacts:
        lines.append(f"  no contact found: the bone never comes within {limits['contact_height_m']} m of the floor at {floor:.4f} m. Is --floor right?")
        return "not verified", lines, record
    return "pass", lines, record


def cmd_check(args):
    model, problem = open_model(args.file)
    if problem:
        print(problem)
        return 1 if problem.startswith("RESULT fail") else 2
    try:
        limits, loose = load_thresholds(args.thresholds)
    except (OSError, ValueError, KeyError) as exc:
        print(f"RESULT not verified: thresholds file {args.thresholds} is unusable: {exc}")
        return 2
    doc = model.doc
    nodes, anims = doc.get("nodes", []), doc.get("animations", [])
    if not anims:
        print("RESULT not verified: the model has no animation clips")
        return 2
    skin_joints = sorted({j for skin in doc.get("skins", []) for j in skin.get("joints", [])})
    joint, message = find_joint(nodes, skin_joints, args.joint)
    if joint is None:
        print(f"blocked: {message}")
        return 2
    picked = list(enumerate(anims))
    if args.clip is not None:
        picked = [(i, a) for i, a in picked if a.get("name") == args.clip or str(i) == args.clip]
        if not picked:
            print(f"blocked: no clip '{args.clip}'. Clips: {', '.join(repr(a.get('name', i)) for i, a in enumerate(anims))}")
            return 2
    print(f"bone '{node_name(nodes, joint)}', up axis {args.up}, floor "
          + (f"{args.floor} m (given)" if args.floor is not None else "= the bone's rest-pose height (assumes the rest pose stands on the floor; pass --floor to state it)"))
    if loose:
        print(f"limits are unverified working values: {', '.join(loose)}")
    states, records = {}, []
    for index, anim in picked:
        state, lines, record = judge_clip(model, anim, joint, args, limits, skin_joints)
        states[anim.get("name") or f"clip {index}"] = state
        records.append({**record, "state": state})
        print(f"clip {index} '{anim.get('name', '')}': {state}")
        print("\n".join(lines))
    print("not computed by this script:")
    for line in NOT_COMPUTED:
        print(f"  - {line}")
    if args.json_out:
        target = pathlib.Path(args.json_out)
        if target.exists():
            print(f"blocked: {target} already exists; choose a new file name")
            return 2
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"file": str(model.path), "clips": records, "not_computed": NOT_COMPUTED}, indent=2) + "\n", encoding="utf-8")
        print(f"table written to {target}")
    failed = [name for name, state in states.items() if state == "fail"]
    unsure = [name for name, state in states.items() if state == "not verified"]
    if failed:
        print("RESULT fail: " + ", ".join(failed))
        return 1
    if unsure:
        print("RESULT not verified: " + ", ".join(unsure))
        return 2
    print("RESULT pass")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    lister = sub.add_parser("list", help="bones and clips")
    lister.add_argument("file")
    check = sub.add_parser("check", help="judge one bone's contact through the clips")
    check.add_argument("file")
    check.add_argument("--joint", required=True, help="bone name, or a unique part of it")
    check.add_argument("--clip", help="clip name or number (default: all)")
    check.add_argument("--up", choices=["y", "z"], default="y")
    check.add_argument("--floor", type=float, help="floor height in metres (default: the bone's rest-pose height)")
    check.add_argument("--fps", type=float, default=30.0)
    check.add_argument("--in-place", action="store_true", help="do not judge sliding")
    check.add_argument("--all", action="store_true", help="print every sample")
    check.add_argument("--json-out", help="write the full per-sample table to this NEW file")
    check.add_argument("--thresholds", type=pathlib.Path, default=THRESHOLDS)
    args = parser.parse_args()
    return {"list": cmd_list, "check": cmd_check}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())

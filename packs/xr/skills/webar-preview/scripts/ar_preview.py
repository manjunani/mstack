#!/usr/bin/env python3
"""Turn a GLB into a phone AR preview whose size matches the real object.

  scale <model.glb> (--size WxHxD | --height H | --longest L)
        Measure the model's bounding box in metres and compare it with the real size you declare.
        Size is width x height x depth in metres (x, y, z; glTF is +Y up). A wrong unit is named
        (for example "100 times too big: the model was probably made in centimetres").
  usdz <model.usdz> [--glb model.glb] [--size ... | --height ... | --longest ...]
        Check a USDZ file: is it a real USDZ archive, does `usdchecker --arkit` accept it, what is its
        size in metres (from `usdcat`), and does it agree with the GLB and the declared size.
  convert <model.glb> --out <new.usdz>
        Run a GLB to USDZ converter when one is installed. This script ships none and installs none;
        without one it ends as blocked and says what to get.
  page --glb <model.glb> [--usdz <model.usdz>] --out <new folder> (--size ... | --height ... | --longest ...)
        [--viewer-script <file or https address>] [--poster <image>] [--title "..."]
        Run the scale check, then write a small page with an AR viewer element and copy the model files
        beside it. The folder must not exist yet.

Nothing here can prove what a phone shows: opening the page in AR on a real device stays a step for a person.
Exit codes: 0 = pass, 1 = fail, 2 = not verified or blocked.
"""
import argparse
import html
import html.parser
import json
import pathlib
import re
import shutil
import subprocess
import sys
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import glb  # noqa: E402

LIMITS = pathlib.Path(__file__).resolve().parent.parent / "references" / "ar_limits.json"
UNITS = ((100.0, "centimetres"), (1000.0, "millimetres"), (39.3701, "inches"), (0.01, "a unit 100 times larger than metres"),
         (0.3048, "feet (model is too small by that factor)"), (3.28084, "feet"))
CONVERTERS = ("usdzconvert", "usd_from_gltf")
CONVERTER_HELP = ("no GLB to USDZ converter found (looked for: " + ", ".join(CONVERTERS) + "). Options: Apple's Reality Converter app or "
                  "USD Python tools (usdzconvert), Google's usd_from_gltf, or export USDZ from Blender. Install one yourself, then run this again.")
NOT_PROVEN = ["that the model appears at the right size on a real phone: open the page on an iPhone (Quick Look) and an Android phone (Scene Viewer)",
              "lighting, shadows and how the model sits on a real surface",
              "that the files are reachable from the phone: AR viewers need them served over https"]


def load_limits(path=LIMITS):
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    return {k: v["value"] for k, v in data["limits"].items()}, [k for k, v in data["limits"].items() if not v.get("verified")]


def declared_size(args):
    """Return (dict of axis index -> metres, 'longest' value or None, error text or None)."""
    given = [bool(args.size), args.height is not None, args.longest is not None]
    if sum(given) != 1:
        return None, None, "declare the real size with exactly one of --size WxHxD, --height H or --longest L (metres). The size is never assumed."
    if args.size:
        parts = re.split(r"[x,*]", args.size.lower().replace("m", ""))
        try:
            values = [float(p) for p in parts]
        except ValueError:
            values = []
        if len(values) != 3 or min(values) <= 0:
            return None, None, f"--size needs three positive numbers in metres like 0.45x0.9x0.45; got '{args.size}'"
        return dict(enumerate(values)), None, None
    if args.height is not None:
        return ({1: args.height}, None, None) if args.height > 0 else (None, None, "--height has to be positive")
    return ({}, args.longest, None) if args.longest > 0 else (None, None, "--longest has to be positive")


def unit_hint(ratio):
    for factor, name in UNITS:
        if abs(ratio / factor - 1) < 0.03:
            return f" That ratio is {factor:g}: the model was probably made in {name}."
    return ""


def compare_size(measured, axes, longest, tolerance, label):
    """Return (rows, failures). measured is [x, y, z] in metres."""
    rows, failures = [], []
    pairs = [("xyz"[a], measured[a], want) for a, want in sorted(axes.items())]
    if longest is not None:
        pairs.append(("longest side", max(measured), longest))
    for name, got, want in pairs:
        off = (got - want) / want * 100
        ok = abs(off) <= tolerance
        rows.append(f"  {label} {name}: measured {got:.4f} m, declared {want:.4f} m, off by {off:+.1f}% -> {'ok' if ok else 'WRONG'}")
        if not ok:
            ratio = got / want if want else 0
            failures.append(f"{label} {name} is {got:.4f} m, declared {want:.4f} m ({ratio:.3g} times the real size).{unit_hint(ratio)}")
    return rows, failures


def measure_glb(path):
    """Return (size list or None, problem text or None, summary)."""
    model = glb.load(path)
    glb.structure(model)
    if not model.readable:
        return None, model.errors[0], None
    if model.errors:
        return None, f"{len(model.errors)} structural errors (first: {model.errors[0]}); run gltf-gate on it", None
    summary = glb.stats(model)
    if not summary["bounds_m"]:
        return None, "the model has no readable bounding box", summary
    return summary["bounds_m"]["size"], None, summary


def cmd_scale(args):
    axes, longest, problem = declared_size(args)
    if problem:
        print(f"blocked: {problem}")
        return 2
    limits, loose = load_limits()
    size, problem, summary = measure_glb(args.glb)
    if problem:
        kind = glb.sniff(args.glb)[0]
        print(f"RESULT not verified: {args.glb}: no such file" if kind == "missing" else f"RESULT fail: {problem}")
        return 2 if kind == "missing" else 1
    print(f"{args.glb}: bounding box {size[0]:.4f} x {size[1]:.4f} x {size[2]:.4f} m (width x, height y, depth z)")
    low = summary["bounds_m"]["min"]
    print(f"  lowest point y = {low[1]:.4f} m; centre x,z = {summary['bounds_m']['centre'][0]:.4f}, {summary['bounds_m']['centre'][2]:.4f}"
          + ("" if abs(low[1]) < 0.01 else "  <- the base is not at y = 0, so the model will float or sink on the surface"))
    rows, failures = compare_size(size, axes, longest, limits["scale_tolerance_pct"], "GLB")
    print("\n".join(rows))
    if loose:
        print(f"  tolerance {limits['scale_tolerance_pct']}% is an unverified working value")
    if failures:
        print("RESULT fail: " + " ".join(failures))
        return 1
    print("RESULT pass")
    return 0


OPS = re.compile(r"^\s*(?:uniform\s+)?(\w+)(\[\])?\s+(xformOp:[\w:]+|extent|xformOpOrder)\s*=\s*(.+)$")
NUMBER = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def usd_bounds(text):
    """Parse flattened usda text. Return (metersPerUnit, upAxis, [min, max] or None, notes)."""
    notes = []
    meters = re.search(r"^\s*metersPerUnit\s*=\s*([-\d.eE+]+)", text, re.M)
    up = re.search(r'^\s*upAxis\s*=\s*"(\w)"', text, re.M)
    meters_per_unit = float(meters.group(1)) if meters else 0.01
    if not meters:
        notes.append("no metersPerUnit in the file; USD then means 0.01 (centimetres)")
    stack = [{"ops": {}, "order": None, "extent": None}]
    worlds = [glb.IDENTITY]
    low, high = [float("inf")] * 3, [float("-inf")] * 3
    unsupported = set()

    def local(prim):
        matrix = glb.IDENTITY
        order = prim["order"] if prim["order"] is not None else []
        for name in order:
            values = prim["ops"].get(name)
            if values is None:
                continue
            kind = name.split(":")[1]
            if kind == "translate" and len(values) == 3:
                op = glb.trs_matrix(values, [0, 0, 0, 1], [1, 1, 1])
            elif kind == "scale" and len(values) == 3:
                op = glb.trs_matrix([0, 0, 0], [0, 0, 0, 1], values)
            elif kind == "transform" and len(values) == 16:
                op = list(values)
            else:
                if any(abs(v) > 1e-9 for v in values) and kind != "orient" or kind == "orient" and values[:1] != [1.0]:
                    unsupported.add(name)
                continue
            matrix = glb.mat_mul(matrix, op)
        return matrix

    def close_prim():
        prim = stack.pop()
        world = glb.mat_mul(worlds[len(stack) - 1], local(prim))
        return prim, world

    pending = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("def ", "over ", "class ")):
            pending.append(True)
            continue
        if stripped == "{" and pending:
            pending.pop()
            stack.append({"ops": {}, "order": None, "extent": None, "children": []})
            continue
        if stripped == "}" and len(stack) > 1:
            prim = stack.pop()
            stack[-1].setdefault("children", []).append(prim)
            continue
        match = OPS.match(line)
        if match and len(stack) > 1:
            name, value = match.group(3), match.group(4)
            if name == "xformOpOrder":
                stack[-1]["order"] = re.findall(r'"(xformOp:[\w:]+)"', value)
            elif name == "extent":
                numbers = [float(n) for n in NUMBER.findall(value)]
                if len(numbers) == 6:
                    stack[-1]["extent"] = (numbers[:3], numbers[3:])
            else:
                stack[-1]["ops"][name] = [float(n) for n in NUMBER.findall(value)]

    def visit(prim, parent):
        world = glb.mat_mul(parent, local(prim))
        if prim.get("extent"):
            lo, hi = prim["extent"]
            for corner in range(8):
                point = glb.transform_point(world, [hi[a] if corner >> a & 1 else lo[a] for a in range(3)])
                for a in range(3):
                    low[a], high[a] = min(low[a], point[a]), max(high[a], point[a])
        for child in prim.get("children", []):
            visit(child, world)

    for prim in stack[0].get("children", []):
        visit(prim, glb.IDENTITY)
    if unsupported:
        notes.append("rotation ops are present and were NOT evaluated (" + ", ".join(sorted(unsupported)) + "); the box may be wrong")
    box = None if low[0] == float("inf") else ([v * meters_per_unit for v in low], [v * meters_per_unit for v in high])
    return meters_per_unit, (up.group(1) if up else "Y"), box, notes, bool(unsupported)


def cmd_usdz(args):
    path = pathlib.Path(args.usdz)
    limits, loose = load_limits()
    if not path.is_file():
        print(f"RESULT not verified: {path}: no such file")
        return 2
    failures, unverified = [], []
    if not zipfile.is_zipfile(path):
        print(f"RESULT fail: {path} is not a USDZ archive ({glb.sniff(path)[1]})")
        return 1
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        names = [e.filename for e in entries]
        print(f"{path}: {path.stat().st_size} bytes, {len(entries)} files inside: {', '.join(names[:8])}")
        if not entries or pathlib.PurePosixPath(names[0]).suffix not in (".usd", ".usda", ".usdc"):
            failures.append(f"the first file in the archive has to be the USD layer; it is '{names[0] if names else 'nothing'}'")
        packed = [e.filename for e in entries if e.compress_type != zipfile.ZIP_STORED]
        if packed:
            failures.append(f"{len(packed)} files are compressed; a USDZ stores files without compression ({packed[0]})")
        inner_text = None
        if entries and names[0].endswith(".usda"):
            inner_text = archive.read(names[0]).decode("utf-8", "replace")

    usdcat, checker = shutil.which("usdcat"), shutil.which("usdchecker")
    text = None
    if usdcat:
        out = subprocess.run([usdcat, "--flatten", str(path)], capture_output=True, text=True, timeout=300)
        if out.returncode == 0 and out.stdout.lstrip().startswith("#usda"):
            text = out.stdout
        else:
            failures.append("usdcat cannot open the file: " + (out.stderr or out.stdout).strip().splitlines()[-1][:160] if (out.stderr or out.stdout).strip() else "usdcat cannot open the file")
    elif inner_text is not None:
        text = inner_text
        print("  usdcat not found; read the text layer inside the archive directly")
    else:
        unverified.append("size of the USDZ (usdcat not found and the layer is binary; usdcat ships with Xcode's command line tools and with OpenUSD)")
    if checker and not failures:
        out = subprocess.run([checker, "--arkit", str(path)], capture_output=True, text=True, timeout=300)
        verdict = out.stdout + out.stderr
        if "Success!" in verdict and "Failed" not in verdict:
            print("  usdchecker --arkit: Success")
        else:
            lines = [line.strip() for line in verdict.splitlines() if line.strip() and "Validation Result" not in line][:8]
            print("  usdchecker --arkit:\n    " + "\n    ".join(lines))
            failures.append("usdchecker --arkit does not accept the file")
    elif not checker:
        unverified.append("AR compliance (usdchecker not found)")

    size = None
    if text:
        meters_per_unit, up, box, notes, rotated = usd_bounds(text)
        print(f"  metersPerUnit {meters_per_unit:g}, upAxis {up}")
        for note in notes:
            print(f"  note: {note}")
        if up != "Y":
            print("  warning: the up axis is not Y; check on a phone that the model stands upright")
        if box is None:
            unverified.append("size of the USDZ (no extent values in the file)")
        elif rotated:
            unverified.append("size of the USDZ (rotation ops not evaluated)")
        else:
            size = [box[1][a] - box[0][a] for a in range(3)]
            print(f"  bounding box {size[0]:.4f} x {size[1]:.4f} x {size[2]:.4f} m (from extent values, translate, scale and matrix ops)")
    axes, longest, problem = declared_size(args)
    if size and not problem:
        rows, wrong = compare_size(size, axes, longest, limits["scale_tolerance_pct"], "USDZ")
        print("\n".join(rows))
        failures.extend(wrong)
    elif not args.glb and problem and size:
        unverified.append("real size (give --size, --height or --longest, or --glb to compare with)")
    if args.glb and size:
        glb_size, glb_problem, _ = measure_glb(args.glb)
        if glb_problem:
            failures.append(f"GLB twin: {glb_problem}")
        else:
            for name, a, b in zip(("smallest", "middle", "largest"), sorted(glb_size), sorted(size)):
                off = abs(a - b) / a * 100 if a else (0.0 if b == 0 else 100.0)
                ok = off <= limits["twin_tolerance_pct"]
                print(f"  twin {name} side: GLB {a:.4f} m, USDZ {b:.4f} m, off by {off:.1f}% -> {'ok' if ok else 'WRONG'}")
                if not ok:
                    ratio = b / a if a else 0
                    failures.append(f"USDZ {name} side is {ratio:.3g} times the GLB's.{unit_hint(ratio)}")
    if loose:
        print("  tolerances are unverified working values")
    if failures:
        print("RESULT fail: " + "; ".join(failures))
        return 1
    if unverified:
        print("RESULT not verified: " + "; ".join(unverified))
        return 2
    print("RESULT pass")
    return 0


def cmd_convert(args):
    source, target = pathlib.Path(args.glb), pathlib.Path(args.out)
    size, problem, _ = measure_glb(source)
    if problem:
        print(f"RESULT fail: the GLB is not usable: {problem}")
        return 1
    if target.exists():
        print(f"blocked: {target} already exists; choose a new file name")
        return 2
    tool = next((shutil.which(name) for name in CONVERTERS if shutil.which(name)), None)
    if not tool:
        print(f"blocked: {CONVERTER_HELP}")
        return 2
    command = [tool, str(source), str(target)]
    print("running: " + " ".join(command) + "   (input then output; check the tool's own --help if it refuses)")
    try:
        out = subprocess.run(command, capture_output=True, text=True, timeout=1800)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"RESULT not verified: the converter did not finish: {exc}")
        return 2
    if not target.is_file() or target.stat().st_size == 0:
        tail = (out.stderr or out.stdout).strip().splitlines()[-2:]
        print(f"RESULT fail: the converter (exit {out.returncode}) wrote no file. " + " | ".join(tail))
        return 1
    print(f"wrote {target}; checking it against the GLB")
    return cmd_usdz(argparse.Namespace(usdz=str(target), glb=str(source), size=None, height=None, longest=None))


class Links(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.found = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in ("src", "href", "ios-src", "poster") and value:
                self.found.append((tag, name, value))


def cmd_page(args):
    axes, longest, problem = declared_size(args)
    if problem:
        print(f"blocked: {problem}")
        return 2
    out = pathlib.Path(args.out)
    if out.exists():
        print(f"blocked: {out} already exists; the page goes into a new folder")
        return 2
    viewer = args.viewer_script
    if not viewer and not args.usdz:
        print("blocked: nothing on the page could open AR. Give --viewer-script (a model-viewer build you host, or its https address) "
              "for Android and the 3D view, or --usdz for iOS Quick Look, or both.")
        return 2
    code = cmd_scale(argparse.Namespace(glb=args.glb, size=args.size, height=args.height, longest=args.longest))
    if code != 0:
        return code
    if args.usdz:
        print("== USDZ twin")
        code = cmd_usdz(argparse.Namespace(usdz=args.usdz, glb=args.glb, size=args.size, height=args.height, longest=args.longest))
        if code == 1:
            return 1
        usdz_state = "pass" if code == 0 else "not verified"
    out.mkdir(parents=True)
    glb_name = pathlib.Path(args.glb).name
    shutil.copy2(args.glb, out / glb_name)
    usdz_name = poster_name = None
    if args.usdz:
        usdz_name = pathlib.Path(args.usdz).name
        shutil.copy2(args.usdz, out / usdz_name)
    if args.poster:
        poster_name = pathlib.Path(args.poster).name
        shutil.copy2(args.poster, out / poster_name)
    script = None
    if viewer:
        if re.match(r"https://", viewer):
            script = viewer
        elif pathlib.Path(viewer).is_file():
            script = pathlib.Path(viewer).name
            shutil.copy2(viewer, out / script)
        else:
            print(f"blocked: --viewer-script '{viewer}' is neither a file nor an https address")
            return 2
    title = html.escape(args.title or pathlib.Path(args.glb).stem)
    parts = ["<!doctype html>", '<html lang="en">', "<head>", '<meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width, initial-scale=1">', f"<title>{title}</title>",
             "<style>body{margin:0;font-family:system-ui,sans-serif}main{max-width:40rem;margin:auto;padding:1rem}"
             "model-viewer{width:100%;height:70vh;background:#eee}a.ar{display:inline-block;margin:1rem 0;font-size:1.1rem}</style>"]
    if script:
        parts.append(f'<script type="module" src="{html.escape(script)}"></script>')
    parts += ["</head>", "<body>", "<main>", f"<h1>{title}</h1>"]
    if script:
        ios = f' ios-src="{html.escape(usdz_name)}"' if usdz_name else ""
        poster = f' poster="{html.escape(poster_name)}"' if poster_name else ""
        parts.append(f'<model-viewer src="{html.escape(glb_name)}"{ios}{poster} alt="{title}" ar ar-modes="webxr scene-viewer quick-look" '
                     'ar-scale="fixed" camera-controls></model-viewer>')
    if usdz_name:
        inner = f'<img src="{html.escape(poster_name)}" alt="{title}" width="240">' if poster_name else "View in your room (iPhone or iPad)"
        parts.append(f'<p><a class="ar" rel="ar" href="{html.escape(usdz_name)}">{inner}</a></p>')
    parts += ["<p>The model is shown at its real size. Move the phone slowly so it can find the floor or table.</p>", "</main>", "</body>", "</html>"]
    (out / "index.html").write_text("\n".join(parts) + "\n", encoding="utf-8")

    reader = Links()
    reader.feed((out / "index.html").read_text(encoding="utf-8"))
    broken = []
    print(f"== page {out / 'index.html'}")
    for tag, name, value in reader.found:
        if value.startswith("https://"):
            print(f"  <{tag} {name}> {value}  (loaded from the network when the page opens; not fetched here)")
            continue
        target = out / value
        good = target.is_file() and target.stat().st_size > 0
        print(f"  <{tag} {name}> {value}: {target.stat().st_size if good else 'MISSING'}" + (" bytes" if good else ""))
        if not good:
            broken.append(value)
    viewers = ("a model-viewer element" if script else "") + (" and " if script and usdz_name else "") + ("a Quick Look link" if usdz_name else "")
    print(f"  AR entry points on the page: {viewers}")
    if script:
        print("  note: the model-viewer attributes (ar, ar-modes, ar-scale=\"fixed\", ios-src) are written from memory; check them against the viewer version you load")
    if not usdz_name:
        print("  no USDZ: iPhones get no Quick Look link; the viewer element may still offer AR where WebXR is available")
    print("not proven by this script:")
    for line in NOT_PROVEN:
        print(f"  - {line}")
    if broken:
        print("RESULT fail: the page refers to missing files: " + ", ".join(broken))
        return 1
    if args.usdz and usdz_state != "pass":
        print("RESULT not verified: the page is written, but the USDZ check could not be completed (see above)")
        return 2
    print("RESULT pass")
    return 0


def add_size(parser):
    parser.add_argument("--size", help="real size in metres, width x height x depth, for example 0.45x0.9x0.45")
    parser.add_argument("--height", type=float, help="real height in metres")
    parser.add_argument("--longest", type=float, help="real length of the longest side in metres")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    scale = sub.add_parser("scale", help="compare the GLB's size with the real size")
    scale.add_argument("glb")
    add_size(scale)
    usdz = sub.add_parser("usdz", help="check a USDZ file")
    usdz.add_argument("usdz")
    usdz.add_argument("--glb", help="the GLB it was made from, to compare sizes")
    add_size(usdz)
    convert = sub.add_parser("convert", help="GLB to USDZ with an installed converter")
    convert.add_argument("glb")
    convert.add_argument("--out", required=True)
    page = sub.add_parser("page", help="write the AR preview page")
    page.add_argument("--glb", required=True)
    page.add_argument("--usdz")
    page.add_argument("--out", required=True, help="NEW folder for the page and the copied model files")
    page.add_argument("--viewer-script", help="a model-viewer build: a local file (copied beside the page) or an https address")
    page.add_argument("--poster", help="an image shown before the model loads and inside the Quick Look link")
    page.add_argument("--title")
    add_size(page)
    args = parser.parse_args()
    return {"scale": cmd_scale, "usdz": cmd_usdz, "convert": cmd_convert, "page": cmd_page}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())

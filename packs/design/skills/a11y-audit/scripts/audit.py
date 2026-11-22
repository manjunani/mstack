#!/usr/bin/env python3
"""Judge an accessibility run: axe-core results plus a keyboard pass, against a saved baseline.

  needs  check that the project can run the scan (node, a Playwright package, its browser,
         axe-core) and say what is missing and how the user can get it
  check  read axe-core JSON and a keyboard log, list what fails, and compare with the baseline

Inputs to check:
  --axe FILE...     axe-core results: one results object, a list of them, or the file
                    written by run_axe.mjs. Violations at the chosen level block.
  --keyboard FILE   the keyboard log: the focus stops in Tab order, each with whether focus
                    was visible (written by run_axe.mjs or with focus_probe.js).
  --snapshot FILE   optional page snapshot (design-review's format): every focusable element
                    in it has to appear among the focus stops of the same view.
The baseline lives in .mstack/a11y-audit/baseline.json under --root. Save it before fixing
(--save-baseline); a later run with --baseline lists what is fixed, what remains, what is new.
A later run that scans fewer pages or fewer rules than the baseline is not verified.

Exit codes: 0 = no violation at the level, every stop shows focus, nothing left to look at
            1 = at least one violation or keyboard failure
            2 = not verified or blocked: a tool is missing, no keyboard log, the scan did not
                run, the run covers less than the baseline, or axe could not decide something
This script never edits the project. It writes only the baseline file, and only when asked.
"""
import argparse
import datetime
import json
import pathlib
import shutil
import sys

LEVEL_TAGS = {"A": {"wcag2a", "wcag21a", "wcag22a"},
              "AA": {"wcag2a", "wcag21a", "wcag22a", "wcag2aa", "wcag21aa", "wcag22aa"}}
BASELINE = pathlib.Path(".mstack") / "a11y-audit" / "baseline.json"
NOT_COVERED = ("no scanner covers: what a screen reader actually says, whether alt text and labels are true, "
               "reading order that makes sense, and anything in a state or page that was not scanned")


class BadInput(Exception):
    pass


# ---------- snapshot reader (format 1; the same reader is repeated in design-review and ui-copy) ----------

def load_json(path):
    try:
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        if isinstance(data, str):  # some browser tools hand back the JSON as a quoted string
            data = json.loads(data)
    except (OSError, ValueError) as exc:
        raise BadInput(f"cannot read {path}: {exc}")
    return data


def views_of(data, path):
    if isinstance(data, dict) and isinstance(data.get("views"), list):
        views = data["views"]
    elif isinstance(data, dict) and "elements" in data:
        views = [data]
    else:
        raise BadInput(f"{path} is not a snapshot: it has neither 'views' nor 'elements'")
    for view in views:
        width = (view.get("viewport") or {}).get("width") if isinstance(view, dict) else None
        if not isinstance(width, (int, float)) or not isinstance(view.get("elements"), list):
            raise BadInput(f"{path}: every view needs viewport.width and a list of elements")
    return views


def label_of(view):
    return f"{view['viewport']['width']:g}/{view.get('theme', 'light')}/{view.get('state', 'default')}"


# ---------- axe results ----------

def axe_runs(path):
    data = load_json(path)
    if isinstance(data, dict) and isinstance(data.get("runs"), list):
        raw = [(r.get("view") or (r.get("results") or {}).get("url") or path, r.get("results")) for r in data["runs"] if isinstance(r, dict)]
    elif isinstance(data, list):
        raw = [((r.get("view") or r.get("url") or f"{path}#{i + 1}") if isinstance(r, dict) else f"{path}#{i + 1}", r) for i, r in enumerate(data)]
    else:
        raw = [((data.get("view") or data.get("url") or str(path)) if isinstance(data, dict) else str(path), data)]
    runs = []
    for label, results in raw:
        if not isinstance(results, dict) or not isinstance(results.get("violations"), list):
            raise BadInput(f"{path}: not axe-core output (no 'violations' list). Pass the JSON that axe.run() returned")
        ran = set()
        for group in ("violations", "passes", "incomplete", "inapplicable"):
            ran |= {r.get("id") for r in results.get(group) or [] if isinstance(r, dict)}
        if not ran:
            raise BadInput(f"{path}: axe reported no rule results at all for {label}, so the scan did not run")
        if str(results.get("url", "")).startswith("about:"):
            raise BadInput(f"{path}: the scan ran on {results['url']}, not on a page")
        runs.append({"label": str(label), "results": results, "rules": len(ran)})
    if not runs:
        raise BadInput(f"{path} holds no axe results")
    return runs


def targets(node):
    target = node.get("target") or []
    return " ".join(" >> ".join(t) if isinstance(t, list) else str(t) for t in target) or (node.get("html") or "?")[:80]


def judge_axe(runs, level):
    wanted = LEVEL_TAGS[level]
    blocks, warns, unsure = [], [], []
    for run in runs:
        for rule in run["results"]["violations"]:
            tags = set(rule.get("tags") or [])
            at_level = not tags or bool(tags & wanted)
            for node in rule.get("nodes") or [{}]:
                row = {"run": run["label"], "rule": rule.get("id", "?"), "target": targets(node), "impact": rule.get("impact") or "",
                       "help": rule.get("help") or rule.get("description") or ""}
                (blocks if at_level else warns).append(row)
        for rule in run["results"].get("incomplete") or []:
            for node in rule.get("nodes") or [{}]:
                unsure.append({"run": run["label"], "rule": rule.get("id", "?"), "target": targets(node), "help": rule.get("help") or ""})
    return blocks, warns, unsure


# ---------- keyboard log ----------

def keyboard_passes(path):
    data = load_json(path)
    passes = data.get("passes") if isinstance(data, dict) and isinstance(data.get("passes"), list) else [data]
    for one in passes:
        if not isinstance(one, dict) or not isinstance(one.get("stops"), list):
            raise BadInput(f"{path}: not a keyboard log (each pass needs a 'stops' list)")
        for stop in one["stops"]:
            if not isinstance(stop, dict) or "selector" not in stop or not isinstance(stop.get("focusVisible"), bool):
                raise BadInput(f"{path}: every stop needs a selector and focusVisible true or false: {json.dumps(stop)[:120]}")
    return passes


def judge_keyboard(passes, snapshot_views):
    blocks = []
    for one in passes:
        view = str(one.get("view") or one.get("url") or "keyboard pass")
        stops = one["stops"]

        def add(problem, selector):
            blocks.append({"run": view, "rule": "keyboard", "target": selector, "impact": "", "help": problem})

        reached = [s["selector"] for s in stops]
        expected = list(one.get("focusable") or [])
        for snap in snapshot_views:
            if label_of(snap) == view:
                expected += [e.get("selector") for e in snap["elements"] if e.get("focusable") and not e.get("disabled") and (e.get("role") or "") != "radio"]
        if not stops:
            add("the Tab key reached nothing on this page", "html")
        for stop in stops:
            if not stop["focusVisible"]:
                add("focus lands here but nothing shows it", stop["selector"])
        run_length = 1
        for before, after in zip(reached, reached[1:]):
            run_length = run_length + 1 if before == after else 1
            if run_length == 3:
                add("focus stays on this element when Tab is pressed: a keyboard trap", after)
        ended = one.get("ended") or ""
        if stops and ended != "wrapped":
            add(f"the pass did not come back to the start (ended: {ended or 'not stated'}); a trap, or more stops than the pass allowed", reached[-1])
        for selector in dict.fromkeys(s for s in expected if s and s not in reached):
            add("can take focus but Tab never reaches it", selector)
        for extra in one.get("checks") or []:
            if isinstance(extra, dict) and extra.get("ok") is False:
                add(f"{extra.get('name', 'keyboard check')} failed: {extra.get('detail', '')}".strip(), str(extra.get("selector") or "page"))
    return blocks


# ---------- commands ----------

def cmd_needs(args):
    root = pathlib.Path(args.root).resolve()
    missing = []
    if shutil.which("node") is None:
        missing.append("node is not on the PATH. The user installs Node.js from nodejs.org or their package manager")
    modules = root / "node_modules"
    driver = next((name for name in ("playwright", "playwright-core", "@playwright/test") if (modules / name).is_dir()), None)
    if driver is None:
        missing.append(f"no Playwright package in {modules}. The user adds it to the project: npm install --save-dev playwright")
    else:
        caches = [pathlib.Path.home() / "Library" / "Caches" / "ms-playwright", pathlib.Path.home() / ".cache" / "ms-playwright",
                  pathlib.Path.home() / "AppData" / "Local" / "ms-playwright"]
        if not any(c.is_dir() and any(c.glob("chromium*")) for c in caches):
            missing.append("Playwright is installed but its Chromium browser is not downloaded. The user runs: npx playwright install chromium")
    if not (modules / "axe-core").is_dir():
        missing.append(f"no axe-core package in {modules}. The user adds it to the project: npm install --save-dev axe-core")
    print(f"project: {root}")
    if missing:
        for line in missing:
            print("missing: " + line)
        print("without these, a host browser tool can still run the scan if it can inject a copy of axe-core the user provides; nothing is installed by this skill")
        print(f"blocked: {len(missing)} thing(s) needed before the scan can run; ask the user")
        return 2
    print(f"found: node, {driver}, a Chromium download, axe-core")
    print("RESULT pass")
    return 0


def cmd_check(args):
    root = pathlib.Path(args.root).resolve()
    baseline_path = pathlib.Path(args.baseline) if isinstance(args.baseline, str) else root / BASELINE
    try:
        runs = [run for path in args.axe for run in axe_runs(path)]
        passes = keyboard_passes(args.keyboard) if args.keyboard else []
        snapshot_views = views_of(load_json(args.snapshot), args.snapshot) if args.snapshot else []
        reviewed = load_json(args.reviewed) if args.reviewed else []
        if not isinstance(reviewed, list) or any(not isinstance(r, dict) or not r.get("rule") or len(str(r.get("reason", "")).strip()) < 8 for r in reviewed):
            raise BadInput(f"{args.reviewed}: each entry needs a rule and a reason of at least 8 characters")
        baseline = None
        if args.baseline is not None:
            if not baseline_path.exists():
                raise BadInput(f"no baseline at {baseline_path}; save one first with --save-baseline")
            baseline = load_json(baseline_path)
        if args.save_baseline and (root / BASELINE).exists() and not args.replace_baseline:
            raise BadInput(f"{root / BASELINE} already exists; compare against it with --baseline, or pass --replace-baseline to start over")
    except BadInput as exc:
        print(str(exc))
        print(f"RESULT not verified: {exc}")
        return 2
    blocks, warns, unsure = judge_axe(runs, args.level)
    blocks += judge_keyboard(passes, snapshot_views)
    looked = [u for u in unsure if any(r["rule"] == u["rule"] and r.get("target", u["target"]) == u["target"] for r in reviewed)]
    unsure = [u for u in unsure if u not in looked]
    engine = (runs[0]["results"].get("testEngine") or {}).get("version", "unknown version")
    print(f"axe-core {engine}, level {args.level}: {len(runs)} scan(s): " + ", ".join(f"{r['label']} ({r['rules']} rules)" for r in runs))
    print(f"keyboard: {len(passes)} pass(es), {sum(len(p['stops']) for p in passes)} focus stops" if passes else "keyboard: no log given")
    for row in blocks:
        impact = f" [{row['impact']}]" if row["impact"] else ""
        print(f"FAIL {row['rule']:24} {row['run']}  {row['target']}{impact}: {row['help']}")
    for row in unsure:
        print(f"LOOK {row['rule']:24} {row['run']}  {row['target']}: axe could not decide; {row['help']}")
    for row in warns:
        print(f"warn {row['rule']:24} {row['run']}  {row['target']}: outside level {args.level}; {row['help']}")
    key = lambda r: (r["run"], r["rule"], r["target"])  # noqa: E731
    now = {key(r) for r in blocks}
    shrink = []
    if baseline is not None:
        before = {tuple(k) for k in baseline.get("failures", [])}
        fixed, remaining, new = before - now, before & now, now - before
        print(f"against the baseline of {baseline.get('saved', '?')}: {len(fixed)} fixed, {len(remaining)} remaining, {len(new)} new")
        for item in sorted(fixed):
            print(f"  fixed      {item[1]:24} {item[0]}  {item[2]}")
        for item in sorted(new):
            print(f"  NEW        {item[1]:24} {item[0]}  {item[2]}")
        have = {r["label"]: r["rules"] for r in runs}
        for label, rules in (baseline.get("scans") or {}).items():
            if label not in have:
                shrink.append(f"the baseline scanned {label}; this run did not")
            elif have[label] < rules:
                shrink.append(f"{label}: this run checked {have[label]} rules, the baseline checked {rules}")
        if baseline.get("keyboard_passes", 0) > len(passes):
            shrink.append(f"the baseline had {baseline['keyboard_passes']} keyboard pass(es); this run has {len(passes)}")
        if baseline.get("level") != args.level:
            shrink.append(f"the baseline was judged at level {baseline.get('level')}, this run at {args.level}")
    if args.save_baseline:
        target = root / BASELINE
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"saved": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "level": args.level,
                                      "scans": {r["label"]: r["rules"] for r in runs}, "keyboard_passes": len(passes),
                                      "failures": sorted(now)}, indent=2) + "\n", encoding="utf-8")
        print(f"baseline saved to {target} with {len(now)} failure(s)")
    print(f"{len(blocks)} failure(s), {len(unsure)} for a human to look at, {len(looked)} looked at, {len(warns)} outside the level")
    print(NOT_COVERED)
    if blocks:
        print(f"RESULT fail: {len(blocks)} accessibility failure(s): {', '.join(sorted({r['rule'] for r in blocks}))}")
        return 1
    gaps = shrink[:]
    if not passes:
        gaps.append("no keyboard log, so focus order and visible focus are unknown")
    if unsure:
        gaps.append(f"{len(unsure)} result(s) axe could not decide; look at each and record it with --reviewed")
    if gaps:
        print("RESULT not verified: " + "; ".join(gaps))
        return 2
    print("RESULT pass")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("needs", help="check that the scan can run in this project")
    p.add_argument("--root", default=".", help="project folder (default: current folder)")
    p = sub.add_parser("check", help="judge axe results and a keyboard log")
    p.add_argument("--axe", nargs="+", required=True, help="axe-core result files")
    p.add_argument("--keyboard", help="keyboard log JSON")
    p.add_argument("--snapshot", help="page snapshot JSON; its focusable elements have to be reached")
    p.add_argument("--level", choices=sorted(LEVEL_TAGS), default="AA", help="WCAG level whose violations block (default AA)")
    p.add_argument("--reviewed", help="JSON list of undecided axe results a person looked at: rule, optional target, reason")
    p.add_argument("--root", default=".", help="project folder that holds .mstack/ (default: current folder)")
    p.add_argument("--save-baseline", action="store_true", help="save this run's failures as the baseline")
    p.add_argument("--replace-baseline", action="store_true", help="with --save-baseline: replace an existing baseline")
    p.add_argument("--baseline", nargs="?", const=True, default=None, help="compare with the saved baseline (or with the given file)")
    args = parser.parse_args()
    return {"needs": cmd_needs, "check": cmd_check}[args.action](args)


if __name__ == "__main__":
    sys.exit(main())

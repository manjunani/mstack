#!/usr/bin/env python3
"""Sort a plan's assumptions by impact and confidence, and fail if a top-ranked risk has no test.

  template FILE --plan PATH   write an empty assumption table (refuses if FILE exists)
  rank FILE                   sort the table, name the weakest link, check the top risks have tests

The file is JSON:
  plan         path of the written plan or spec this is about (must exist under --root)
  failure      the story: it is some months later and the plan failed; what happened
  assumptions  at least three, each:
     id          A-01, A-02, ...
     statement   what must be true for the plan to work
     impact      1 to 5: how much of the plan is lost if this is wrong (5 = all of it)
     confidence  1 to 5: how sure, on evidence (5 = seen it; 1 = hope)
     evidence    what the confidence rests on; required for confidence 4 or 5
     depends_on  optional list of ids this assumption rests on
     reversible  optional true/false: can the plan be undone cheaply if this proves wrong
     test        {"what": "...", "cost": "2 hours", "pass": "...", "fail": "..."}

How the ranking works:
  - confidence 4 or 5 with no evidence is counted as 2
  - an assumption is no surer than the weakest one it depends on
  - risk = impact x (6 - confidence as counted); highest first, then higher impact, then lower confidence
  - top-ranked = the first --top rows (default 3), plus every row with impact 4 or more and counted confidence 2 or less
What rank enforces:
  - every top-ranked assumption has a test with what, a cost, a pass line and a fail line; pass and fail differ
  - the cost reads as an amount of time ("30 min", "2 hours", "1 day"), so the cheapest test can be named

Exit codes: 0 = pass: every top-ranked risk has a test
            1 = fail: a top-ranked risk has no test, or its test has no pass or fail line
            2 = blocked: no file, no written plan, fewer than three assumptions, or a broken table
The script writes <name>.ranked.md beside the input and never changes the input.
"""
import argparse
import json
import pathlib
import re
import sys

PLACEHOLDER = re.compile(r"\b(tbd|todo|fixme|to be decided|fill in)\b|\?\?\?|<[A-Za-z][^<>]{0,40}>", re.I)
ID = re.compile(r"^A-\d{2,}$")
COST = re.compile(r"(\d+(?:\.\d+)?)\s*(min|minute|minutes|h|hr|hrs|hour|hours|d|day|days|w|wk|week|weeks)\b", re.I)
MINUTES = {"m": 1, "h": 60, "d": 480, "w": 2400}


def said(value, least=3):
    return isinstance(value, str) and len(value.strip()) >= least and not PLACEHOLDER.search(value)


def scale(value):
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 5


def cost_minutes(text):
    match = COST.search(text) if isinstance(text, str) else None
    return float(match.group(1)) * MINUTES[match.group(2)[0].lower()] if match else None


def load(path, root):
    """Return (data, None) or (None, [reasons it cannot be ranked])."""
    if not path.exists():
        return None, [f"{path} does not exist. Run: assumptions.py template {path} --plan <the plan file>"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return None, [f"{path} is not valid JSON ({exc})"]
    if not isinstance(data, dict) or not isinstance(data.get("assumptions"), list):
        return None, [f"{path} needs an 'assumptions' list"]
    reasons = []
    plan = data.get("plan")
    if not said(plan):
        reasons.append("plan is empty: a premortem needs a written plan or spec to examine. Name its path")
    else:
        found = (root / plan).resolve()
        if not found.is_file() or not found.is_relative_to(root):
            reasons.append(f"plan '{plan}' is not a file under {root}")
    if not said(data.get("failure"), 30):
        reasons.append("failure is empty or too short: write what happened in the story where the plan failed")
    rows = [a for a in data["assumptions"] if isinstance(a, dict)]
    if len(rows) < 3:
        reasons.append(f"{len(rows)} assumption(s): the table needs at least three to rank")
    ids = set()
    for position, row in enumerate(rows, 1):
        label = row.get("id") or f"assumption {position}"
        if not ID.match(str(row.get("id", ""))):
            reasons.append(f"{label}: id must look like A-01")
        if row.get("id") in ids:
            reasons.append(f"{label}: id is used twice")
        ids.add(row.get("id"))
        if not said(row.get("statement"), 8):
            reasons.append(f"{label}: statement is empty or a placeholder")
        for field in ("impact", "confidence"):
            if not scale(row.get(field)):
                reasons.append(f"{label}: {field} must be a whole number from 1 to 5; it is {row.get(field)!r}")
    for row in rows:
        depends = row.get("depends_on", [])
        if not isinstance(depends, list):
            reasons.append(f"{row.get('id')}: depends_on must be a list of ids")
            continue
        for other in depends:
            if other not in ids or other == row.get("id"):
                reasons.append(f"{row.get('id')}: depends on '{other}', which is not another assumption in the table")
    data["assumptions"] = rows
    return (data, None) if not reasons else (None, reasons)


def counted_confidence(rows):
    """Return ({id: counted confidence}, {id: note}, cycle or None)."""
    by_id = {r["id"]: r for r in rows}
    own, notes = {}, {}
    for row in rows:
        own[row["id"]] = row["confidence"]
        if row["confidence"] >= 4 and not said(row.get("evidence"), 8):
            own[row["id"]] = 2
            notes[row["id"]] = f"confidence {row['confidence']} with no evidence, counted as 2"
    counted, visiting = {}, []

    def visit(rid):
        if rid in counted:
            return None
        if rid in visiting:
            return visiting[visiting.index(rid):] + [rid]
        visiting.append(rid)
        value, weakest = own[rid], None
        for other in by_id[rid].get("depends_on", []):
            cycle = visit(other)
            if cycle:
                return cycle
            if counted[other] < value:
                value, weakest = counted[other], other
        visiting.pop()
        counted[rid] = value
        if weakest:
            notes[rid] = (notes[rid] + "; " if rid in notes else "") + f"rests on {weakest} (confidence {counted[weakest]}), counted as {value}"
        return None

    for row in rows:
        cycle = visit(row["id"])
        if cycle:
            return None, None, cycle
    return counted, notes, None


def cmd_template(root, args):
    if args.file.exists():
        print(f"blocked: {args.file} already exists; it is not overwritten")
        return 2
    empty = {"id": "A-01", "statement": "", "impact": None, "confidence": None, "evidence": "", "depends_on": [],
             "test": {"what": "", "cost": "", "pass": "", "fail": ""}}
    args.file.parent.mkdir(parents=True, exist_ok=True)
    args.file.write_text(json.dumps({"plan": args.plan, "failure": "", "assumptions": [empty]}, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.file}: no failure story and one empty assumption. rank refuses it until it holds at least three.")
    print("RESULT pass")
    return 0


def cmd_rank(root, args):
    data, reasons = load(args.file, root)
    if reasons:
        for line in reasons:
            print("  REFUSED  " + line)
        print(f"blocked: {len(reasons)} problem(s) in the assumption table; nothing was ranked")
        return 2
    rows = data["assumptions"]
    counted, notes, cycle = counted_confidence(rows)
    if cycle:
        print(f"blocked: assumptions depend on each other in a circle: {' -> '.join(cycle)}")
        return 2
    for row in rows:
        row["_counted"] = counted[row["id"]]
        row["_risk"] = row["impact"] * (6 - counted[row["id"]])
    ranked = sorted(rows, key=lambda r: (-r["_risk"], -r["impact"], r["_counted"], r["id"]))
    top = [r for position, r in enumerate(ranked) if position < args.top or (r["impact"] >= 4 and r["_counted"] <= 2)]

    problems, warnings = [], []
    for row in top:
        test = row.get("test") if isinstance(row.get("test"), dict) else {}
        if not said(test.get("what"), 8):
            problems.append(f"{row['id']} (risk {row['_risk']}) has no test. Name the smallest thing that would show whether it is true")
            continue
        for field in ("pass", "fail"):
            if not said(test.get(field), 8):
                problems.append(f"{row['id']}: its test has no {field} line. Say what result counts as {field}")
        if said(test.get("pass"), 8) and said(test.get("fail"), 8):
            if test["pass"].strip().lower() == test["fail"].strip().lower():
                problems.append(f"{row['id']}: the pass line and the fail line are the same")
            elif not re.search(r"\d", test["pass"] + test["fail"]):
                warnings.append(f"{row['id']}: neither line has a number in it. Could someone else tell pass from fail?")
        if cost_minutes(test.get("cost")) is None:
            problems.append(f"{row['id']}: the test's cost must be an amount of time such as '30 min', '2 hours' or '1 day'; it is {test.get('cost')!r}")

    header = "| rank | id | risk | impact | confidence | assumption | test |\n|---|---|---|---|---|---|---|"
    lines = []
    for position, row in enumerate(ranked, 1):
        test = row.get("test") if isinstance(row.get("test"), dict) else {}
        shown = str(row["confidence"]) if row["_counted"] == row["confidence"] else f"{row['confidence']} (counted {row['_counted']})"
        mark = " *" if row in top else ""
        lines.append(f"| {position}{mark} | {row['id']} | {row['_risk']} | {row['impact']} | {shown} | {row['statement']} | "
                     f"{(test.get('what') or '-') if said(test.get('what'), 8) else '-'} |")
    print(header)
    print("\n".join(lines))
    print(f"\n* top-ranked: {', '.join(r['id'] for r in top)}  (risk = impact x (6 - counted confidence))")
    for rid, note in notes.items():
        print(f"  note  {rid}: {note}")
    for row in top:
        if row.get("reversible") is False:
            print(f"  note  {row['id']}: marked as not reversible. If it is wrong, the plan cannot be undone cheaply")
    worst = ranked[0]
    print(f"\nWeakest link: {worst['id']} - {worst['statement']}")
    testable = [r for r in top if isinstance(r.get("test"), dict) and cost_minutes(r["test"].get("cost")) is not None and said(r["test"].get("what"), 8)]
    if testable:
        cheapest = min(testable, key=lambda r: (cost_minutes(r["test"]["cost"]), ranked.index(r)))
        for label, row in (("Test for the weakest link", worst if worst in testable else None), ("Cheapest test among the top risks", cheapest)):
            if row:
                print(f"{label}: {row['id']}, {row['test']['cost']}: {row['test']['what']}")
                print(f"    pass: {row['test'].get('pass')}\n    fail: {row['test'].get('fail')}")
    out = args.file.with_name(args.file.stem + ".ranked.md")
    out.write_text(f"# Premortem: {data['plan']}\n\n**The failure story.** {data['failure']}\n\n{header}\n" + "\n".join(lines)
                   + f"\n\n\\* top-ranked. Weakest link: {worst['id']}.\n", encoding="utf-8")
    print(f"\nranked table written to {out}")
    for line in warnings:
        print("  warn  " + line)
    for line in problems:
        print("  FAIL  " + line)
    if problems:
        print(f"RESULT fail: {len(problems)} problem(s) with the tests of the top-ranked risks")
        return 1
    print("RESULT pass")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path.cwd(), help="project folder the plan path is checked against (default: current folder)")
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("template", help="write an empty assumption table")
    p.add_argument("file", type=pathlib.Path)
    p.add_argument("--plan", required=True, help="path of the written plan or spec")
    p = sub.add_parser("rank", help="sort the table and check the top risks have tests")
    p.add_argument("file", type=pathlib.Path)
    p.add_argument("--top", type=int, default=3, help="how many rows count as top-ranked (default 3)")
    args = parser.parse_args()
    return {"template": cmd_template, "rank": cmd_rank}[args.action](args.root.resolve(), args)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Check an options file: many candidates first, then cuts with reasons, then two or three survivors.

  template FILE --question Q --target N   write an empty options file (refuses if FILE exists)
  freeze FILE                             record that the full list exists, before anything is judged
  check FILE                              check the judged list against the frozen one

The file is JSON:
  question   what the options answer
  target     how many distinct candidates to produce before judging (at least --min-target, default 8)
  grounding  what was read or heard first: [{"where": "<path>", "note": "..."}] or [{"source": "user said", "note": "..."}]
  axes       optional: the parts of the subject to cover; every axis then needs at least one option
  options    [{"id": "O-01", "title": "...", "how": "one line", "axis": "...", "status": "candidate"}]
             after freeze, each option becomes
               "status": "rejected", "reason": "<why it was cut>"      or
               "status": "survivor", "basis": "<what in the project or the user's words supports it>", "where": "<optional path>"

What freeze enforces (the list must be complete before any of it is judged):
  - at least one grounding entry; a "where" path must exist under --root
  - the number of distinct options reaches the target (near-identical titles count once)
  - every axis has an option, when axes are listed
  - no option has a status other than "candidate", and none has a reason or a basis yet
What check enforces:
  - the list was frozen, and no frozen option was removed or retitled since
  - no option is still "candidate"
  - every rejected option has a reason of its own; every survivor states its basis
  - two or three options survive
A reason used word for word on three or more options is a warning.

Exit codes: 0 = pass
            1 = fail: a rule above is broken
            2 = blocked or not verified: no file, not valid JSON, or check on a list that was never frozen
The script writes only the options file it is given (template and freeze).
"""
import argparse
import datetime
import hashlib
import json
import pathlib
import re
import sys

PLACEHOLDER = re.compile(r"\b(tbd|todo|fixme|to be decided|fill in)\b|\?\?\?|<[A-Za-z][^<>]{0,40}>", re.I)
STOP = set("a an the and or of to in on for with by as at from into via use using add make do".split())
ID = re.compile(r"^O-\d{2,}$")


def said(value, least=1):
    return isinstance(value, str) and len(value.strip()) >= least and not PLACEHOLDER.search(value)


def words(title):
    return frozenset(w for w in re.findall(r"[a-z0-9]+", str(title).lower()) if w not in STOP)


def title_print(option):
    return hashlib.sha256(" ".join(sorted(words(option.get("title")))).encode("utf-8")).hexdigest()[:12]


def load(path):
    if not path.exists():
        print(f"blocked: {path} does not exist. Run: options.py template {path} --question \"...\" --target 12")
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        print(f"blocked: {path} is not valid JSON ({exc})")
        return None
    if not isinstance(data, dict) or not isinstance(data.get("options"), list):
        print(f"blocked: {path} needs an 'options' list")
        return None
    data["options"] = [o for o in data["options"] if isinstance(o, dict)]
    return data


def distinct(options):
    """Group options whose titles are the same idea in other words. Return (count, [(kept id, duplicate id)])."""
    kept, twins = [], []
    for option in options:
        mine = words(option.get("title"))
        match = None
        for other in kept:
            theirs = words(other.get("title"))
            union = mine | theirs
            if union and len(mine & theirs) / len(union) >= 0.8:
                match = other
                break
        if match is None:
            kept.append(option)
        else:
            twins.append((match.get("id"), option.get("id")))
    return len(kept), twins


def basics(data, root, min_target):
    """Problems that apply both before and after judging."""
    problems = []
    if not said(data.get("question"), 8):
        problems.append("question is empty or a placeholder")
    target = data.get("target")
    if not isinstance(target, int) or isinstance(target, bool) or target < min_target:
        problems.append(f"target must be a whole number of at least {min_target}; it is {target!r}")
    grounding = data.get("grounding")
    if not isinstance(grounding, list) or not grounding:
        problems.append("grounding is empty: record what was read in the project or what the user said before listing options")
    for position, item in enumerate(grounding if isinstance(grounding, list) else [], 1):
        if not isinstance(item, dict) or not said(item.get("note"), 5):
            problems.append(f"grounding {position}: needs a note saying what was learned")
        elif item.get("where"):
            found = (root / re.sub(r":\d+(-\d+)?$", "", str(item["where"]))).resolve()
            if not found.exists() or not found.is_relative_to(root):
                problems.append(f"grounding {position}: '{item['where']}' was not found under {root}")
        elif item.get("source") != "user said":
            problems.append(f"grounding {position}: needs a 'where' path, or \"source\": \"user said\"")
    seen = set()
    for position, option in enumerate(data["options"], 1):
        label = option.get("id") or f"option {position}"
        if not ID.match(str(option.get("id", ""))):
            problems.append(f"{label}: id must look like O-01")
        if option.get("id") in seen:
            problems.append(f"{label}: id is used twice")
        seen.add(option.get("id"))
        if not said(option.get("title"), 3):
            problems.append(f"{label}: title is empty or a placeholder")
    axes = data.get("axes")
    if isinstance(axes, list) and axes:
        used = {o.get("axis") for o in data["options"]}
        for axis in axes:
            if axis not in used:
                problems.append(f"axis '{axis}' has no option")
        for option in data["options"]:
            if option.get("axis") not in axes:
                problems.append(f"{option.get('id')}: axis '{option.get('axis')}' is not one of the listed axes")
    return problems


def cmd_template(args):
    if args.file.exists():
        print(f"blocked: {args.file} already exists; it is not overwritten")
        return 2
    data = {"question": args.question, "target": args.target, "grounding": [],
            "options": [{"id": "O-01", "title": "", "how": "", "status": "candidate"}]}
    args.file.parent.mkdir(parents=True, exist_ok=True)
    args.file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.file}: no grounding and one empty option. It cannot be frozen until {args.target} distinct options are listed.")
    print("RESULT pass")
    return 0


def cmd_freeze(args):
    data = load(args.file)
    if data is None:
        return 2
    root = args.root.resolve()
    problems = basics(data, root, args.min_target)
    options = data["options"]
    judged = [o.get("id") for o in options if o.get("status", "candidate") != "candidate" or o.get("reason") or o.get("basis")]
    if judged:
        problems.append(f"already judged: {', '.join(str(j) for j in judged)}. List every candidate before cutting any; set them back to 'candidate' and remove reason and basis")
    count, twins = distinct(options)
    for kept, twin in twins:
        print(f"  note  {twin} repeats {kept} in other words; the pair counts once")
    target = data.get("target") if isinstance(data.get("target"), int) else args.min_target
    if count < target:
        problems.append(f"{count} distinct options; the target is {target}. Add {target - count} more before judging")
    if "frozen" in data and not problems:
        print(f"  note  the list was frozen before ({data['frozen'].get('count')} options); freezing again with {count}")
    for line in problems:
        print("  FAIL  " + line)
    if problems:
        print(f"RESULT fail: not frozen; {len(problems)} problem(s)")
        return 1
    data["frozen"] = {"count": count, "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                      "options": {o["id"]: title_print(o) for o in options}}
    args.file.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"frozen: {count} distinct options recorded in {args.file}. Now judge every one of them.")
    print("RESULT pass")
    return 0


def cmd_check(args):
    data = load(args.file)
    if data is None:
        return 2
    root = args.root.resolve()
    frozen = data.get("frozen")
    if not isinstance(frozen, dict) or not isinstance(frozen.get("options"), dict):
        print("RESULT not verified: the list was never frozen, so nothing shows the candidates were all listed before any was cut. Run: options.py freeze")
        return 2
    problems, warnings = basics(data, root, args.min_target), []
    options = data["options"]
    by_id = {o.get("id"): o for o in options}
    for oid, mark in frozen["options"].items():
        if oid not in by_id:
            problems.append(f"{oid}: was in the frozen list and has been removed. A cut option stays, as 'rejected' with its reason")
        elif title_print(by_id[oid]) != mark:
            problems.append(f"{oid}: its title changed after the freeze. Add a new option instead of rewriting one")
    late = [o.get("id") for o in options if o.get("id") not in frozen["options"]]
    if late:
        print(f"  note  added after the freeze: {', '.join(str(i) for i in late)}")
    reasons = {}
    survivors = []
    for option in options:
        oid, status = option.get("id"), option.get("status")
        if status == "rejected":
            if not said(option.get("reason"), 12):
                problems.append(f"{oid}: rejected with no reason (a sentence saying why this one was cut)")
            else:
                reasons.setdefault(option["reason"].strip().lower(), []).append(oid)
        elif status == "survivor":
            survivors.append(option)
            if not said(option.get("basis"), 12):
                problems.append(f"{oid}: a survivor must state its basis: what in the project or in the user's words supports it")
            if option.get("where"):
                found = (root / re.sub(r":\d+(-\d+)?$", "", str(option["where"]))).resolve()
                if not found.exists() or not found.is_relative_to(root):
                    problems.append(f"{oid}: basis points at '{option['where']}', which was not found under {root}")
        elif status == "candidate" or status is None:
            problems.append(f"{oid}: not judged yet. Every option ends as 'rejected' or 'survivor'")
        else:
            problems.append(f"{oid}: status '{status}' is not 'rejected' or 'survivor'")
    for reason, ids in reasons.items():
        if len(ids) >= 3:
            warnings.append(f"the same reason is given word for word for {', '.join(ids)}: \"{reason[:60]}\"")
    if not 2 <= len(survivors) <= 3:
        problems.append(f"{len(survivors)} survivors; the short list holds two or three")
    rejected = sum(1 for o in options if o.get("status") == "rejected")
    print(f"checked {args.file}: {len(options)} options ({frozen.get('count')} distinct at the freeze), {rejected} rejected, {len(survivors)} survivors")
    for option in survivors:
        print(f"  survivor  {option.get('id')}  {option.get('title')}: {option.get('basis')}")
    for line in warnings:
        print("  warn  " + line)
    for line in problems:
        print("  FAIL  " + line)
    if problems:
        print(f"RESULT fail: {len(problems)} problem(s) in the options file")
        return 1
    print("RESULT pass")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path.cwd(), help="project folder that 'where' paths are checked against (default: current folder)")
    parser.add_argument("--min-target", type=int, default=8, help="smallest target accepted (default 8)")
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("template", help="write an empty options file")
    p.add_argument("file", type=pathlib.Path)
    p.add_argument("--question", required=True)
    p.add_argument("--target", type=int, default=12, help="distinct candidates to list before judging (default 12)")
    for name, text in (("freeze", "record the full list before judging"), ("check", "check the judged list")):
        p = sub.add_parser(name, help=text)
        p.add_argument("file", type=pathlib.Path)
    args = parser.parse_args()
    return {"template": cmd_template, "freeze": cmd_freeze, "check": cmd_check}[args.action](args)


if __name__ == "__main__":
    sys.exit(main())

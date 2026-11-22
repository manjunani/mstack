#!/usr/bin/env python3
"""Check an intent file: the short statement of what the user wants, with a ledger of where each point came from.

  template FILE --title T   write an empty intent file to fill in (refuses if FILE exists)
  check FILE                check the restatement and every ledger entry
  confirm FILE --words W    record the user's yes, tied to the content as it is now
  show FILE                 print the restatement and the ledger as plain text to show the user

The file is JSON:
  title        what the work is called
  restatement  six slots: outcome, user, why_now, success, constraint, out_of_scope
  entries      the ledger; each entry has
                 id            I-01, I-02, ...
                 statement     one fact, decision or question
                 status        "settled" or "open"
                 changes_build true if a different answer would change what gets built
                 source        (settled entries) one of: user said, user chose, found in repo, found in docs, assumed
                 where         (found in repo / found in docs) the path it was read from, optionally path:line
                 rejected      (user chose) the alternative that was turned down
                 reason        (user chose) why, in the user's terms

What check enforces:
  - all six restatement slots are filled, with no placeholder text
  - every settled entry has one of the five source labels
  - "user chose" names the rejected alternative and a reason
  - "found in ..." points at a file that exists under --root
  - nothing that changes the build is "assumed" or "open"
  - the user's confirmation exists and was made on the content as it is now

Exit codes: 0 = pass
            1 = fail: a rule above is broken; the lines say which
            2 = blocked or not verified: no file, not valid JSON, or the user has not confirmed
This script reads the project and writes only the intent file it is given.
"""
import argparse
import datetime
import hashlib
import json
import pathlib
import re
import sys

SLOTS = ["outcome", "user", "why_now", "success", "constraint", "out_of_scope"]
SOURCES = ["user said", "user chose", "found in repo", "found in docs", "assumed"]
PLACEHOLDER = re.compile(r"\b(tbd|todo|fixme|lorem ipsum|to be decided|fill in)\b|\?\?\?|<[A-Za-z][^<>]{0,40}>|^\W*$", re.I)
ID = re.compile(r"^I-\d{2,}$")


def filled(value):
    return isinstance(value, str) and value.strip() and not PLACEHOLDER.search(value)


def fingerprint(data):
    core = {"restatement": data.get("restatement"), "entries": data.get("entries")}
    return hashlib.sha256(json.dumps(core, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def load(path):
    if not path.exists():
        print(f"blocked: {path} does not exist. Run: intent.py template {path} --title \"...\"")
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        print(f"blocked: {path} is not valid JSON ({exc})")
        return None
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list) or not isinstance(data.get("restatement"), dict):
        print(f"blocked: {path} needs a 'restatement' object and an 'entries' list")
        return None
    return data


def cmd_template(args):
    if args.file.exists():
        print(f"blocked: {args.file} already exists; it is not overwritten")
        return 2
    data = {
        "title": args.title,
        "restatement": {slot: "" for slot in SLOTS},
        "entries": [
            {"id": "I-01", "statement": "", "status": "open", "changes_build": True},
        ],
    }
    args.file.parent.mkdir(parents=True, exist_ok=True)
    args.file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.file}: six empty restatement slots and one open entry. It fails check until filled in.")
    print("RESULT pass")
    return 0


def examine(data, root):
    """Return (problems, notes). Problems fail the check; notes are shown and do not."""
    problems, notes = [], []
    restatement = data["restatement"]
    for slot in SLOTS:
        if not filled(restatement.get(slot)):
            problems.append(f"restatement: '{slot}' is empty or a placeholder")
    entries = data["entries"]
    if not entries:
        problems.append("ledger: no entries. Record where each point of the restatement came from")
    seen = set()
    for number, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            problems.append(f"entry {number}: not an object")
            continue
        label = entry.get("id") or f"entry {number}"
        if not ID.match(str(entry.get("id", ""))):
            problems.append(f"{label}: id must look like I-01")
        if entry.get("id") in seen:
            problems.append(f"{label}: id is used twice")
        seen.add(entry.get("id"))
        if not filled(entry.get("statement")):
            problems.append(f"{label}: statement is empty or a placeholder")
        if not isinstance(entry.get("changes_build"), bool):
            problems.append(f"{label}: changes_build must be true or false")
        changes = entry.get("changes_build") is True
        status = entry.get("status")
        if status == "open":
            if changes:
                problems.append(f"{label}: open and it changes the build. Ask: {entry.get('statement', '')}")
            else:
                notes.append(f"{label}: open, does not change the build: {entry.get('statement', '')}")
            continue
        if status != "settled":
            problems.append(f"{label}: status must be 'settled' or 'open'")
            continue
        source = entry.get("source")
        if source not in SOURCES:
            problems.append(f"{label}: no provenance label. source must be one of: {', '.join(SOURCES)}")
            continue
        if source == "user chose":
            if not filled(entry.get("rejected")):
                problems.append(f"{label}: a user decision must name the rejected alternative")
            if not filled(entry.get("reason")):
                problems.append(f"{label}: a user decision must give the reason")
        if source in ("found in repo", "found in docs"):
            where = entry.get("where")
            if not filled(where):
                problems.append(f"{label}: '{source}' must say where (a path)")
            else:
                target = re.sub(r":\d+(-\d+)?$", "", where.strip())
                found = (root / target).resolve()
                if not found.exists() or not found.is_relative_to(root):
                    problems.append(f"{label}: '{where}' was not found under {root}")
        if source == "assumed":
            if changes:
                problems.append(f"{label}: assumed, and it changes the build. Ask the user: {entry.get('statement', '')}")
            else:
                notes.append(f"{label}: assumed default (say it out loud so it can be rejected): {entry.get('statement', '')}")
    return problems, notes


def cmd_check(args):
    data = load(args.file)
    if data is None:
        return 2
    root = args.root.resolve()
    problems, notes = examine(data, root)
    entries = [e for e in data["entries"] if isinstance(e, dict)]
    counts = {s: sum(1 for e in entries if e.get("status") == "settled" and e.get("source") == s) for s in SOURCES}
    open_count = sum(1 for e in entries if e.get("status") == "open")
    print(f"checked {args.file}: {len(entries)} entries; " + ", ".join(f"{n} {s}" for s, n in counts.items() if n)
          + (f", {open_count} open" if open_count else ""))
    for line in notes:
        print("  note  " + line)
    for line in problems:
        print("  FAIL  " + line)
    if problems:
        print(f"RESULT fail: {len(problems)} problem(s) in the intent file")
        return 1
    confirmed = data.get("confirmed")
    if not isinstance(confirmed, dict) or not filled(confirmed.get("words")):
        print("blocked: the user has not confirmed the restatement. Show it (intent.py show), wait for a yes, then run confirm")
        return 2
    if confirmed.get("fingerprint") != fingerprint(data):
        print("blocked: the file changed after the user confirmed it. Show the new restatement and confirm again")
        return 2
    print(f"  confirmed {confirmed.get('date')}: \"{confirmed.get('words')}\"")
    print("RESULT pass")
    return 0


def cmd_confirm(args):
    data = load(args.file)
    if data is None:
        return 2
    problems, _ = examine(data, args.root.resolve())
    if problems:
        for line in problems:
            print("  FAIL  " + line)
        print(f"RESULT fail: not confirmed; {len(problems)} problem(s) must be fixed before the user is asked")
        return 1
    if not filled(args.words):
        print("blocked: --words must carry the user's own reply")
        return 2
    data["confirmed"] = {"words": args.words.strip(), "date": datetime.date.today().isoformat(), "fingerprint": fingerprint(data)}
    args.file.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"recorded the confirmation in {args.file} (content fingerprint {data['confirmed']['fingerprint']})")
    print("RESULT pass")
    return 0


def cmd_show(args):
    data = load(args.file)
    if data is None:
        return 2
    print(f"Intent: {data.get('title', '')}\n")
    names = {"outcome": "Outcome", "user": "For whom", "why_now": "Why now", "success": "Success looks like",
             "constraint": "Constraint", "out_of_scope": "Out of scope"}
    for slot in SLOTS:
        print(f"  {names[slot]}: {data['restatement'].get(slot) or '(empty)'}")
    groups = [("Decided by you", ("user chose",)), ("You said", ("user said",)), ("Read from the project", ("found in repo", "found in docs")),
              ("My assumptions (say so if one is wrong)", ("assumed",))]
    entries = [e for e in data["entries"] if isinstance(e, dict)]
    for heading, sources in groups:
        rows = [e for e in entries if e.get("status") == "settled" and e.get("source") in sources]
        if rows:
            print(f"\n{heading}:")
        for e in rows:
            extra = ""
            if e.get("source") == "user chose":
                extra = f" (instead of: {e.get('rejected')}; because: {e.get('reason')})"
            elif e.get("where"):
                extra = f" ({e.get('where')})"
            print(f"  {e.get('id')}  {e.get('statement')}{extra}")
    still_open = [e for e in entries if e.get("status") == "open"]
    if still_open:
        print("\nStill open:")
        for e in still_open:
            print(f"  {e.get('id')}  {e.get('statement')}" + ("  [changes the build]" if e.get("changes_build") else ""))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path.cwd(), help="project folder that 'where' paths are checked against (default: current folder)")
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("template", help="write an empty intent file")
    p.add_argument("file", type=pathlib.Path)
    p.add_argument("--title", required=True, help="what the work is called")
    p = sub.add_parser("check", help="check the restatement and the ledger")
    p.add_argument("file", type=pathlib.Path)
    p = sub.add_parser("confirm", help="record the user's yes")
    p.add_argument("file", type=pathlib.Path)
    p.add_argument("--words", required=True, help="the user's reply, as they wrote it")
    p = sub.add_parser("show", help="print the restatement and ledger for the user")
    p.add_argument("file", type=pathlib.Path)
    args = parser.parse_args()
    return {"template": cmd_template, "check": cmd_check, "confirm": cmd_confirm, "show": cmd_show}[args.action](args)


if __name__ == "__main__":
    sys.exit(main())

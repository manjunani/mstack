#!/usr/bin/env python3
"""Check a research notes file: every claim has a source and a label, and conclusions do not rest on one source.

  notes_check.py notes.md                    check the notes
  notes_check.py notes.md --sources saved/   also confirm that each "saved" file exists in this folder
  notes_check.py --template > notes.md       print an empty notes file in the expected form (not written anywhere)

The notes file is Markdown. Each claim is one list item that starts with "claim:" or "conclusion:",
followed by indented "key: value" lines:

  - claim: The quay fee rose to 40 in 2025.
    label: quoted              quoted | paraphrased | inferred
    url: https://example.org/fees
    saved: fees-2025.txt       a saved copy of the page, in the --sources folder
    accessed: 2026-11-22       the date the page was read
    quote: "the fee is 40 per night"
  - conclusion: Fees went up faster than inflation.
    label: inferred
    from: C1, C3               the claims it rests on, numbered C1, C2 ... in the order they appear

Rules:
  - a claim needs a label and a source: url or saved, and with a url either a saved copy or an accessed date
  - a "quoted" claim needs its quote
  - an "inferred" claim names what it is inferred from (from:), or it is an assumption and fails
  - a conclusion needs from: and fails when every claim it rests on comes from one single source
    (warned, not failed, when it says "single source" in its own text, which states the limit openly)
  - the accessed date is a real date, not in the future

Structure only: this does not prove a claim is true or that a quote is in its source (use cite-check).

Exit codes: 0 = every claim and conclusion meets the rules
            1 = fail: a claim with no source or label, an unsupported inference, a conclusion on one source
            2 = not verified or blocked: the file holds no claims, a saved file is missing, bad input
"""
import argparse
import datetime
import pathlib
import re
import sys

LABELS = ("quoted", "paraphrased", "inferred")
TEMPLATE = """# Research notes: <question>

Question: <the question, in the user's words>
Searched: <date>, budget <n> searches and <n> page reads

- claim: <one fact, as found>
  label: quoted
  url: <address>
  saved: <file in the sources folder>
  accessed: <YYYY-MM-DD>
  quote: "<exact words>"
- conclusion: <the answer>
  label: inferred
  from: C1, C2
"""


def parse(text):
    items, current = [], None
    for number, line in enumerate(text.splitlines(), 1):
        head = re.match(r"^\s*[-*]\s+(claim|conclusion)\s*:\s*(.*)$", line, re.I)
        if head:
            current = {"kind": head.group(1).lower(), "text": head.group(2).strip(), "line": number, "fields": {}}
            items.append(current)
            continue
        field = re.match(r"^\s+([a-z]+)\s*:\s*(.*)$", line, re.I)
        if current and field:
            current["fields"][field.group(1).lower()] = field.group(2).strip()
        elif current and line.strip() and not line.startswith((" ", "\t")):
            current = None
    return items


def source_key(fields):
    url = fields.get("url", "").split("#")[0].rstrip("/").lower()
    host = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
    return url or fields.get("saved", "").lower(), host


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("notes", nargs="?", type=pathlib.Path, help="the notes file")
    parser.add_argument("--sources", type=pathlib.Path, help="folder that holds the saved copies")
    parser.add_argument("--template", action="store_true", help="print an empty notes file and stop")
    args = parser.parse_args()
    if args.template:
        print(TEMPLATE)
        print("RESULT pass: template printed")
        return 0
    if not args.notes:
        print("blocked: name the notes file")
        return 2
    try:
        items = parse(args.notes.read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"blocked: the notes file could not be read ({exc})")
        return 2
    claims = [item for item in items if item["kind"] == "claim"]
    conclusions = [item for item in items if item["kind"] == "conclusion"]
    if not claims:
        print("RESULT not verified: the notes hold no 'claim:' items, so there is nothing to check")
        return 2

    failures, warnings, missing_files = [], [], []
    today = datetime.date.today()
    for number, item in enumerate(claims, 1):
        item["id"], f = f"C{number}", item["fields"]
        where = f"C{number} (line {item['line']})"
        label = f.get("label", "").lower()
        if label not in LABELS:
            failures.append(f"{where}: label is '{label or 'missing'}', expected one of {', '.join(LABELS)}")
        if label == "inferred":
            if not f.get("from"):
                failures.append(f"{where}: inferred with nothing it is inferred from; mark it as an assumption or add from:")
            continue
        if not (f.get("url") or f.get("saved")):
            failures.append(f"{where}: no source (url or saved): \"{item['text'][:80]}\"")
            continue
        if f.get("url") and not (f.get("saved") or f.get("accessed")):
            failures.append(f"{where}: url without a saved copy or an access date")
        if f.get("url") and not re.match(r"^https?://\S+$", f["url"]):
            failures.append(f"{where}: '{f['url']}' is not a web address")
        if label == "quoted" and not f.get("quote"):
            failures.append(f"{where}: labelled quoted but has no quote")
        if f.get("accessed"):
            try:
                day = datetime.date.fromisoformat(f["accessed"])
                if day > today:
                    failures.append(f"{where}: accessed date {day} is in the future")
            except ValueError:
                failures.append(f"{where}: accessed '{f['accessed']}' is not a date like 2026-11-22")
        if f.get("saved") and args.sources and not (args.sources / f["saved"]).is_file():
            missing_files.append(f"{where}: saved copy {f['saved']} is not in {args.sources}")
    by_id = {item["id"]: item for item in claims}
    for number, item in enumerate(conclusions, 1):
        where = f"conclusion {number} (line {item['line']})"
        refs = re.findall(r"C\d+", item["fields"].get("from", ""))
        unknown = [ref for ref in refs if ref not in by_id]
        if not refs:
            failures.append(f"{where}: no from: line naming the claims it rests on")
            continue
        if unknown:
            failures.append(f"{where}: rests on {', '.join(unknown)}, which are not claims in this file")
            continue
        keys, hosts = set(), set()
        for ref in refs:
            key, host = source_key(by_id[ref]["fields"])
            if key:
                keys.add(key)
                hosts.add(host or key)
        if len(hosts) <= 1:
            text = f"{where}: rests on a single source ({next(iter(hosts), 'none')})"
            if "single source" in item["text"].lower():
                warnings.append(text + "; the conclusion says so itself")
            else:
                failures.append(text + "; find an independent second source or say 'single source' in the conclusion")

    labels = {label: sum(1 for c in claims if c["fields"].get("label", "").lower() == label) for label in LABELS}
    print(f"notes-check {args.notes}: {len(claims)} claim(s) ({', '.join(f'{n} {l}' for l, n in labels.items())}), {len(conclusions)} conclusion(s)")
    for line in failures:
        print(f"  FAIL  {line}")
    for line in warnings:
        print(f"  warn  {line}")
    for line in missing_files:
        print(f"  missing  {line}")
    print("limit: this checks structure only, not whether the claims are true or the quotes are in their sources (cite-check does that)")
    if failures:
        print(f"RESULT fail: {len(failures)} problem(s); first: {failures[0][:200]}")
        return 1
    if missing_files:
        print(f"RESULT not verified: {len(missing_files)} saved copy(ies) are missing")
        return 2
    print(f"RESULT pass: {len(claims)} claim(s) sourced and labelled, {len(conclusions)} conclusion(s) on more than one source or marked single source")
    return 0


if __name__ == "__main__":
    sys.exit(main())

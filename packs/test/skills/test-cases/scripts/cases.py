#!/usr/bin/env python3
"""Check a table of test cases against the requirement lines of a spec.

  ids    list the requirement lines found in the spec
  check  every requirement has at least one case; every case has exactly one specific expected result

Requirement lines: a line of the spec that starts with an id of the form R-001 (after an optional
list marker, checkbox, table bar or bold mark). This is the id format shared with the product pack.

Case table: one or more Markdown tables in the cases file. Each needs these columns (any order,
any letter case); every other column is treated as an input:

  id        the case id, unique in the file
  covers    one or more requirement ids, for example "R-002" or "R-002, R-005"
  expected  one observable result

`check` reports a case when its expected result is
  - empty or a placeholder (TBD, TODO, ?, ...),
  - two results at once ("400 or 422", "either", "and/or", "200/204"),
  - a vague phrase with nothing observable ("works", "as expected", "correctly", "properly", "handled", "gracefully", ...).
It also reports a covers id that is not in the spec, a repeated case id, and two cases in one table
with the same inputs and different expected results.

Exit codes: 0 = pass, 1 = fail (problems are listed), 2 = not verified (a file is missing, the spec has
no requirement lines, or the cases file has no table with id, covers and expected columns)
"""
import argparse
import pathlib
import re
import sys

REQ_LINE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+|\|\s*)?(?:\[[ xX]\]\s+)?[*_`]{0,2}(R-\d{3,})\b[*_`]{0,2}[:.)\s|-]*(.*)$")
REQ_ID = re.compile(r"\bR-\d{3,}\b")
PLACEHOLDER = re.compile(r"^\W*(tbd|todo|fixme|n/?a|none|xxx|\?+|\.\.\.|…|-+|same as above|see above|ditto)?\W*$", re.I)
ALTERNATIVE = re.compile(r"\bor\b|\beither\b|\band/or\b|\bmaybe\b|\bpossibly\b|\bdepending\b|\be\.g\.|\betc\b|\b\d{3}\s*/\s*\d{3}\b", re.I)
VAGUE = re.compile(r"\bas expected\b|\bworks?\b|\bworking\b|\bcorrect(ly)?\b|\bproper(ly)?\b|\bappropriate(ly)?\b|\bgracefully\b|"
                   r"\bhandle[sd]?\b|\breasonabl[ey]\b|\bsensibl[ey]\b|\bshould be fine\b|\bvalid (result|response|output)\b|\bsuccessfully\b|\bas intended\b", re.I)
BARE = {"error", "an error", "errors", "fail", "fails", "failure", "success", "succeeds", "ok", "okay", "pass", "passes", "valid", "invalid", "true or false"}
ID_COLUMNS = {"id", "case", "case id", "test", "test id"}
COVERS_COLUMNS = {"covers", "requirement", "requirements", "req", "reqs"}
EXPECTED_COLUMNS = {"expected", "expected result", "expected outcome", "expect"}


def read_requirements(path):
    found, repeats = {}, []
    for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        match = REQ_LINE.match(line)
        if not match:
            continue
        rid, text = match.group(1), match.group(2).strip().strip("|").strip()
        if rid in found:
            repeats.append((rid, number))
        else:
            found[rid] = (number, text)
    return found, repeats


def split_row(line):
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|") and not text.endswith("\\|"):
        text = text[:-1]
    return [cell.replace("\\|", "|").strip() for cell in re.split(r"(?<!\\)\|", text)]


def read_cases(path):
    """Return (cases, table_count). A case is a dict with id, covers, expected, inputs, line, table."""
    cases, tables, header, columns = [], 0, None, {}
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for number, line in enumerate(lines, 1):
        if "|" not in line:
            header = None
            continue
        cells = split_row(line)
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c) and any(cells):
            continue
        lowered = [c.lower().strip("*_` ") for c in cells]
        is_header = (set(lowered) & ID_COLUMNS) and (set(lowered) & COVERS_COLUMNS) and (set(lowered) & EXPECTED_COLUMNS)
        if is_header:
            header = lowered
            tables += 1
            columns = {
                "id": next(i for i, c in enumerate(lowered) if c in ID_COLUMNS),
                "covers": next(i for i, c in enumerate(lowered) if c in COVERS_COLUMNS),
                "expected": next(i for i, c in enumerate(lowered) if c in EXPECTED_COLUMNS),
            }
            continue
        if header is None:
            continue
        cells += [""] * (len(header) - len(cells))
        special = set(columns.values())
        cases.append({
            "id": cells[columns["id"]], "covers": cells[columns["covers"]], "expected": cells[columns["expected"]],
            "inputs": tuple((header[i], cells[i]) for i in range(len(header)) if i not in special),
            "line": number, "table": tables,
        })
    return cases, tables


def expected_problem(text):
    stripped = text.strip().strip("`*_ ")
    if PLACEHOLDER.match(stripped):
        return "no expected result" if not stripped else f"expected is a placeholder ('{text.strip()}')"
    if stripped.lower().rstrip(".") in BARE:
        return f"expected is only '{stripped}': say what is returned, shown or stored"
    # words inside quotes or backticks are literal output ("name or email is required"), not the tester's hedging
    bare = re.sub(r"\"[^\"]*\"|'[^']*'|`[^`]*`", " ", stripped)
    hit = ALTERNATIVE.search(bare)
    if hit:
        return f"expected allows more than one result ('{hit.group(0)}'): split the case or choose the one right answer"
    hit = VAGUE.search(bare)
    if hit:
        return f"expected is not observable ('{hit.group(0)}'): name the value, status, message or state"
    return None


def cmd_ids(args):
    if not args.spec.is_file():
        print(f"RESULT not verified: spec file not found: {args.spec}")
        return 2
    found, repeats = read_requirements(args.spec)
    for rid, (number, text) in found.items():
        print(f"  {rid}  line {number}: {text[:100]}")
    for rid, number in repeats:
        print(f"  note: {rid} also starts line {number}; the first line is used")
    if not found:
        print("RESULT not verified: no line of the spec starts with an id like R-001")
        return 2
    print(f"{len(found)} requirement line(s)")
    print("RESULT pass")
    return 0


def cmd_check(args):
    for label, path in (("spec", args.spec), ("cases", args.cases)):
        if not path.is_file():
            print(f"RESULT not verified: {label} file not found: {path}")
            return 2
    requirements, repeats = read_requirements(args.spec)
    if not requirements:
        print(f"RESULT not verified: no line of {args.spec} starts with an id like R-001, so there is nothing to check the cases against")
        return 2
    cases, tables = read_cases(args.cases)
    if not tables:
        print(f"RESULT not verified: {args.cases} has no Markdown table with id, covers and expected columns")
        return 2

    problems, per_req, seen_ids, by_inputs = [], {rid: [] for rid in requirements}, {}, {}
    for case in cases:
        label = f"case {case['id'] or '(no id)'} (line {case['line']})"
        if not case["id"]:
            problems.append(f"{label}: no id")
        elif case["id"] in seen_ids:
            problems.append(f"{label}: id already used on line {seen_ids[case['id']]}")
        else:
            seen_ids[case["id"]] = case["line"]
        covered = REQ_ID.findall(case["covers"])
        if not covered:
            problems.append(f"{label}: covers names no requirement id")
        for rid in covered:
            if rid in per_req:
                per_req[rid].append(case["id"])
            else:
                problems.append(f"{label}: covers {rid}, which is not a requirement line of the spec")
        fault = expected_problem(case["expected"])
        if fault:
            problems.append(f"{label}: {fault}")
        if case["inputs"] and any(value for _, value in case["inputs"]):
            twin = by_inputs.get((case["table"], case["inputs"]))
            if twin is None:
                by_inputs[(case["table"], case["inputs"])] = case
            elif twin["expected"].strip().lower() != case["expected"].strip().lower():
                problems.append(f"{label}: same inputs as case {twin['id']} but a different expected result")
            else:
                problems.append(f"{label}: repeats case {twin['id']} exactly")
    for rid, ids in per_req.items():
        if not ids:
            number, text = requirements[rid]
            problems.append(f"{rid} (spec line {number}) has no case: {text[:80]}")

    print(f"spec: {args.spec}  ({len(requirements)} requirement lines)")
    print(f"cases: {args.cases}  ({len(cases)} cases in {tables} table(s))")
    for rid, ids in per_req.items():
        print(f"  {rid}  {len(ids):>2} case(s)  {' '.join(ids[:12])}")
    for rid, number in repeats:
        print(f"  note: {rid} also starts spec line {number}; the first line is used")
    for problem in problems:
        print(f"  problem: {problem}")
    if not cases:
        print("RESULT fail: the case table has a header and no rows")
        return 1
    if problems:
        print(f"RESULT fail: {len(problems)} problem(s) above")
        return 1
    print("RESULT pass")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("ids", help="list the requirement lines of a spec")
    p.add_argument("--spec", type=pathlib.Path, required=True, help="the spec or contract file")
    p = sub.add_parser("check", help="check the cases against the spec")
    p.add_argument("--spec", type=pathlib.Path, required=True, help="the spec or contract file")
    p.add_argument("--cases", type=pathlib.Path, required=True, help="the Markdown file with the case table(s)")
    args = parser.parse_args()
    return {"ids": cmd_ids, "check": cmd_check}[args.action](args)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Audit an .xlsx workbook for broken formulas and hard-coded numbers, straight from the file. Read-only.

  audit.py <book.xlsx> [--sheet NAME] [--max-show 20]

An .xlsx file is a zip of XML parts. This script reads them with zipfile and xml.etree and reports:
  - cells that hold an error (#REF!, #DIV/0!, #VALUE!, #NAME?, #N/A, #NUM!, #NULL!), and formulas that contain #REF!
  - a number typed where its neighbours on both sides hold the same formula (an overwritten formula)
  - a formula that differs from the same formula on both sides of it, along a row or down a column
  - formulas that refer to empty cells, and formulas that refer to other workbooks
  - numbers typed inside formulas, such as =B4*0.18
  - hidden sheets, which are read like the others

What is NOT read: nothing is recalculated, so the script sees the values saved in the file; a formula saved
without a result cannot be judged. Macros, pivot tables, charts, conditional formats, data validation, comments
and the contents of linked workbooks are not read. Named ranges, table references such as Table1[Amount],
whole-column references such as A:A and array formulas are not resolved. When the workbook uses one of these,
it is listed under "could not check". Old .xls, .xlsb and .ods files are not read at all.

The report keeps three lists apart: findings, checked and fine, could not check.
Exit codes: 0 = no blocking finding (warnings may be listed) and nothing in the workbook went unread
            1 = error cells, or numbers typed over formulas
            2 = not verified or blocked: the workbook uses something this script does not read, or is not an .xlsx
"""
import argparse
import collections
import json
import pathlib
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

# --- shared block: report (the same text is in every mstack-data script) ---
class Report:
    """Keeps three lists apart: findings, checked and fine, could not check."""

    def __init__(self):
        self.fails, self.warns, self.fine, self.unchecked = [], [], [], []

    def fail(self, text):
        self.fails.append(text)

    def warn(self, text):
        self.warns.append(text)

    def ok(self, text):
        self.fine.append(text)

    def skip(self, text):
        self.unchecked.append(text)

    def as_dict(self):
        return {"findings": [{"level": "fail", "text": t} for t in self.fails] + [{"level": "warn", "text": t} for t in self.warns],
                "checked_and_fine": self.fine, "could_not_check": self.unchecked}

    def show(self):
        print(f"\nFINDINGS ({len(self.fails) + len(self.warns)})")
        for text in self.fails:
            print(f"  [fail] {text}")
        for text in self.warns:
            print(f"  [warn] {text}")
        print(f"\nCHECKED AND FINE ({len(self.fine)})")
        for text in self.fine:
            print(f"  {text}")
        print(f"\nCOULD NOT CHECK ({len(self.unchecked)})")
        for text in self.unchecked:
            print(f"  {text}")
        print()

    def finish(self, why=None):
        """Print the three lists and the RESULT line; return the exit code."""
        self.show()
        if self.fails:
            print(f"RESULT fail: {why or self.fails[0]}" + (f" (and {len(self.fails) - 1} more)" if len(self.fails) > 1 and not why else ""))
            return 1
        if self.unchecked:
            more = f" (and {len(self.unchecked) - 1} more)" if len(self.unchecked) > 1 else ""
            print(f"RESULT not verified: {self.unchecked[0]}{more}")
            return 2
        if self.warns:
            print(f"{len(self.warns)} warning(s) above do not block; report them with the result.")
        print("RESULT pass")
        return 0


def blocked(text):
    print(f"blocked: {text}")
    sys.exit(2)
# --- end of shared block ---

LIMITS_FILE = pathlib.Path(__file__).resolve().parent.parent / "references" / "limits.json"
FALLBACK = {"max_uncompressed_mb": 300, "max_range_cells": 20000, "plain_constants": [0, 1, 2, 10, 100, 1000]}
CELL = r"(\$?)([A-Z]{1,3})(\$?)([0-9]{1,7})"
REF = re.compile(r"(?:(?P<sheet>'(?:[^']|'')+'|[A-Za-z0-9_.\[\]]+)!)?(?<![A-Za-z0-9_.$])" + CELL + r"(?::" + CELL + r")?(?![A-Za-z0-9_(])")
EXTERNAL = re.compile(r"\[(\d+|[^\]]*\.xl\w*)\]")
NUMBER_IN_FORMULA = re.compile(r"(?<![A-Za-z0-9_.$§])\d+(?:\.\d+)?(?![A-Za-z0-9_.§(])")


def load_limits():
    limits, lines = dict(FALLBACK), []
    try:
        data = json.loads(LIMITS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return limits, [f"limits file not readable ({LIMITS_FILE.name}); built-in defaults used, unverified"]
    for name, entry in data.items():
        if name in limits and isinstance(entry, dict) and "value" in entry:
            limits[name] = entry["value"]
            if not entry.get("verified"):
                lines.append(f"{name} = {entry['value']} is an unverified default (checked {entry.get('checked', 'never')})")
    return limits, lines


def local(tag):
    return tag.rsplit("}", 1)[-1]


def col_number(letters):
    number = 0
    for ch in letters:
        number = number * 26 + ord(ch) - 64
    return number


def col_letters(number):
    out = ""
    while number:
        number, rest = divmod(number - 1, 26)
        out = chr(65 + rest) + out
    return out


def split_ref(ref):
    match = re.fullmatch(r"\$?([A-Z]{1,3})\$?(\d+)", ref)
    return (int(match.group(2)), col_number(match.group(1))) if match else None


def outside_strings(formula):
    """The formula with the inside of every "text" blanked, so that cell names in text are not read as references."""
    return re.sub(r'"[^"]*"', lambda m: '"' + " " * (len(m.group(0)) - 2) + '"', formula)


def relative_form(formula, row, col):
    """Rewrite each reference as an offset from the cell, so that a formula filled down or across reads the same."""
    def swap(match):
        parts = []
        for abs_col, letters, abs_row, digits in (match.group(2, 3, 4, 5), match.group(6, 7, 8, 9)):
            if letters is None:
                continue
            c = f"C{col_number(letters)}" if abs_col else f"C[{col_number(letters) - col}]"
            r = f"R{digits}" if abs_row else f"R[{int(digits) - row}]"
            parts.append(r + c)
        return (match.group("sheet") + "!" if match.group("sheet") else "") + ":".join(parts)
    return REF.sub(swap, outside_strings(formula))


def read_sheet(archive, path, strings):
    """Return {(row, col): {"v": text, "t": type, "f": formula or None, "norm": relative form}} and the count of array formulas."""
    cells, shared, arrays = {}, {}, 0
    root = ET.fromstring(archive.read(path))
    for element in root.iter():
        if local(element.tag) != "c" or "r" not in element.attrib:
            continue
        place = split_ref(element.attrib["r"])
        if place is None:
            continue
        kind, value, formula, norm = element.attrib.get("t", "n"), None, None, None
        for child in element:
            name = local(child.tag)
            if name == "v":
                value = child.text
            elif name == "is":
                value = "".join(t.text or "" for t in child.iter() if local(t.tag) == "t")
            elif name == "f":
                formula = child.text or ""
                if child.attrib.get("t") == "array":
                    arrays += 1
                if child.attrib.get("t") == "shared" and "si" in child.attrib:
                    if formula:
                        shared[child.attrib["si"]] = relative_form(formula, *place)
                    norm = ("shared", child.attrib["si"])
        if kind == "s" and value is not None:
            try:
                value = strings[int(value)]
            except (ValueError, IndexError):
                pass
        if formula is not None and norm is None:
            norm = relative_form(formula, *place)
        cells[place] = {"v": value, "t": kind, "f": formula, "norm": norm}
    for cell in cells.values():
        if isinstance(cell["norm"], tuple):
            cell["norm"] = shared.get(cell["norm"][1], "?shared")
    return cells, arrays


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("workbook", help="an .xlsx or .xlsm file")
    parser.add_argument("--sheet", help="audit only this sheet")
    parser.add_argument("--max-show", type=int, default=20, help="how many cells to name per finding (default 20)")
    args = parser.parse_args()
    limits, limit_lines = load_limits()

    try:
        with open(args.workbook, "rb") as handle:
            head = handle.read(8)
    except OSError as exc:
        blocked(f"cannot read {args.workbook}: {exc.strerror}")
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        blocked(f"{args.workbook} is an old binary workbook (.xls) or is password-protected; save it as .xlsx without a password")
    if not zipfile.is_zipfile(args.workbook):
        blocked(f"{args.workbook} is not an .xlsx file (it is not a zip container); a CSV has no formulas to audit")
    archive = zipfile.ZipFile(args.workbook)
    names = set(archive.namelist())
    if "xl/workbook.xml" not in names:
        blocked(f"{args.workbook} is a zip file but not a workbook: xl/workbook.xml is missing" + (" (.xlsb is not read)" if "xl/workbook.bin" in names else ""))
    size = sum(info.file_size for info in archive.infolist())
    if size > limits["max_uncompressed_mb"] * 1024 * 1024:
        blocked(f"the workbook unpacks to {size // (1024 * 1024)} MB, over the limit of {limits['max_uncompressed_mb']} MB")
    try:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = {r.attrib.get("Id"): r.attrib.get("Target", "") for r in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels")).iter() if local(r.tag) == "Relationship"}
        strings = []
        if "xl/sharedStrings.xml" in names:
            for item in ET.fromstring(archive.read("xl/sharedStrings.xml")):
                strings.append("".join(t.text or "" for t in item.iter() if local(t.tag) == "t"))
    except (ET.ParseError, KeyError) as exc:
        blocked(f"the workbook's XML could not be read: {exc}")

    sheets, defined = [], 0
    for element in workbook.iter():
        if local(element.tag) == "sheet":
            rid = next((v for k, v in element.attrib.items() if local(k) == "id"), None)
            target = rels.get(rid, "")
            path = target.lstrip("/") if target.startswith("/") else "xl/" + target
            sheets.append({"name": element.attrib.get("name", "?"), "path": path, "hidden": element.attrib.get("state", "visible") != "visible"})
        elif local(element.tag) == "definedName" and not element.attrib.get("name", "").startswith("_xlnm."):
            defined += 1
    report = Report()
    print(f"SHEET AUDIT {args.workbook}: {len(sheets)} sheet(s)")
    print("  nothing is recalculated: the values are the ones saved in the file")
    for line in limit_lines:
        print(f"  note: {line}")
    if args.sheet and args.sheet not in [s["name"] for s in sheets]:
        blocked(f"no sheet named '{args.sheet}'; the workbook holds: {', '.join(s['name'] for s in sheets)}")

    books = {}
    for sheet in sheets:
        if sheet["path"] not in names or "/worksheets/" not in sheet["path"]:
            report.skip(f"sheet '{sheet['name']}' is not a worksheet (a chart sheet or macro sheet) and was not read")
            continue
        try:
            books[sheet["name"]] = read_sheet(archive, sheet["path"], strings)
        except ET.ParseError as exc:
            report.skip(f"sheet '{sheet['name']}' could not be parsed: {exc}")

    show = lambda cells: ", ".join(cells[:args.max_show]) + (f" and {len(cells) - args.max_show} more" if len(cells) > args.max_show else "")
    plain = {float(v) for v in limits["plain_constants"]}
    totals = collections.Counter()
    arrays_total, uses_tables, uses_whole = 0, 0, 0
    for sheet in sheets:
        name = sheet["name"]
        if name not in books or (args.sheet and name != args.sheet):
            continue
        cells, arrays = books[name]
        arrays_total += arrays
        at = lambda place: f"{name}!{col_letters(place[1])}{place[0]}"
        formulas = {p: c for p, c in cells.items() if c["f"] is not None}
        totals["cells"] += len(cells)
        totals["formulas"] += len(formulas)
        if sheet["hidden"]:
            report.warn(f"sheet '{name}' is hidden ({len(cells)} cells, {len(formulas)} formulas); it was read like the others")

        errors = [f"{at(p)} {c['v']}" for p, c in sorted(cells.items()) if c["t"] == "e" or (c["f"] and "#REF!" in c["f"])]
        if errors:
            report.fail(f"{len(errors)} error cell(s): {show(errors)}")
        unsaved = [at(p) for p, c in sorted(formulas.items()) if c["v"] is None]
        if unsaved:
            report.skip(f"{len(unsaved)} formula(s) on '{name}' have no saved result, so errors in them cannot be seen ({show(unsaved)}); open and save the file in a spreadsheet program, then audit again")

        def is_number(cell):
            return cell is not None and cell["f"] is None and cell["t"] == "n" and cell["v"] not in (None, "")

        typed, odd = {}, {}
        for (row, col), cell in sorted(cells.items()):
            for label, before, after in (("column", (row - 1, col), (row + 1, col)), ("row", (row, col - 1), (row, col + 1))):
                one, two = formulas.get(before), formulas.get(after)
                if not one or not two or one["norm"] != two["norm"]:
                    continue
                if is_number(cell):
                    typed.setdefault((row, col), f"{at((row, col))} = {cell['v']} (formulas on both sides in its {label})")
                elif cell["f"] is not None and cell["norm"] != one["norm"]:
                    odd.setdefault((row, col), f"{at((row, col))} ={cell['f']} (its {label} neighbours hold ={one['f'] or 'a shared formula'})")
        if typed:
            report.fail(f"{len(typed)} number(s) typed where a formula is expected: {show(list(typed.values()))}")
        if odd:
            report.warn(f"{len(odd)} formula(s) differ from the same formula on both sides: {show(list(odd.values()))}")

        external, empties, constants = [], [], []
        for place, cell in sorted(formulas.items()):
            text = outside_strings(cell["f"])
            if EXTERNAL.search(text):
                external.append(at(place))
            uses_tables += bool(re.search(r"[A-Za-z0-9_]\[|\[@|\[#", EXTERNAL.sub("", text)))
            uses_whole += bool(re.search(r"(?<![A-Za-z0-9_$])\$?[A-Z]{1,3}:\$?[A-Z]{1,3}(?![A-Za-z0-9_(])|(?<![A-Za-z0-9_$:.])\$?\d+:\$?\d+(?![A-Za-z0-9_.])", text))
            for match in REF.finditer(text):
                target = match.group("sheet")
                if target and EXTERNAL.search(target):
                    continue
                target = target.strip("'").replace("''", "'") if target else name
                if target not in books:
                    continue
                first = (int(match.group(5)), col_number(match.group(3)))
                last = (int(match.group(9)), col_number(match.group(7))) if match.group(7) else first
                rows, cols = sorted((first[0], last[0])), sorted((first[1], last[1]))
                if (rows[1] - rows[0] + 1) * (cols[1] - cols[0] + 1) > limits["max_range_cells"]:
                    continue
                other = books[target][0]
                filled = any((r, c) in other and (other[(r, c)]["f"] is not None or other[(r, c)]["v"] not in (None, ""))
                             for r in range(rows[0], rows[1] + 1) for c in range(cols[0], cols[1] + 1))
                if not filled:
                    empties.append(f"{at(place)} -> {match.group(0)}")
            stripped = REF.sub("§", text)
            found = sorted({m.group(0) for m in NUMBER_IN_FORMULA.finditer(stripped) if float(m.group(0)) not in plain})
            if found:
                constants.append(f"{at(place)} ({', '.join(found)})")
        if external:
            report.warn(f"{len(external)} formula(s) on '{name}' read from another workbook: {show(external)}")
        if empties:
            report.warn(f"{len(empties)} reference(s) on '{name}' point at empty cells: {show(empties)}")
        if constants:
            report.warn(f"{len(constants)} formula(s) on '{name}' hold a typed number: {show(constants)}")
        if formulas:
            for label, hit in (("error cells", errors), ("numbers typed over formulas", typed), ("formulas that break their row or column", odd),
                               ("references to empty cells", empties), ("links to other workbooks", external), ("typed numbers inside formulas", constants)):
                if not hit:
                    report.ok(f"'{name}': no {label} ({len(formulas)} formulas read)")
        else:
            report.ok(f"'{name}': {len(cells)} cells and no formulas")

    if not totals["cells"]:
        report.fail("no cells were read from the workbook")
    if any(n.startswith("xl/externalLinks/") for n in names):
        report.skip("the workbook links to other files; what those files hold was not read")
    if "xl/vbaProject.bin" in names:
        report.skip("the workbook holds macros; they were not read and can change any cell")
    pivots = sum(1 for n in names if n.startswith("xl/pivotTables/") and n.endswith(".xml"))
    if pivots:
        report.skip(f"{pivots} pivot table(s) were not read")
    if defined:
        report.skip(f"{defined} named range(s) are defined; formulas that use a name were not followed to its cells")
    if uses_tables:
        report.skip(f"{uses_tables} formula(s) use table references such as Table1[Column]; those were not resolved")
    if uses_whole:
        report.skip(f"{uses_whole} formula(s) use whole-column or whole-row references; those were not checked for empty cells")
    if arrays_total:
        report.skip(f"{arrays_total} array formula(s) were read as text only")
    print(f"  read {totals['cells']} cells, {totals['formulas']} formulas")
    return report.finish()


if __name__ == "__main__":
    sys.exit(main())

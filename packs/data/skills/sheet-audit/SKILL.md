---
name: sheet-audit
description: Audits an .xlsx workbook from the file for error cells, numbers typed over formulas, formulas that break their row or column, links to empty cells or other workbooks, hidden sheets, and what it did not read. Use when asked "can I trust this spreadsheet", "check this Excel model", or before numbers from a workbook go into a report. Not for building or editing spreadsheets, or for CSV files (use data-profile).
license: MIT
metadata:
  pack: data
  version: 0.2.1
  needs: python3
---

# Sheet audit

Produces a list of cells to look at, each with its address, and a list of the workbook's parts that were not read.

## Done when

- `scripts/audit.py` ran on the workbook and its RESULT line is in the reply.
- Every finding names the sheet and cell.
- The reply states what was not read: no recalculation, and any macros, pivot tables, links, named ranges or table references the script listed.

End in exactly one state: **pass** (no blocking finding and nothing unread), **fail** (error cells, or numbers typed over formulas), **not verified** (the workbook uses parts this script does not read, or formulas have no saved result), or **blocked** (not an .xlsx, or unreadable).

## Needs

| Need | Check | If missing |
|---|---|---|
| python3 | `python3 --version` | end as blocked |
| An .xlsx or .xlsm file | the script checks the real type | ask the user to save as .xlsx; end as blocked |

## Steps

The script is `scripts/audit.py` in this skill's folder. In Claude Code that is `"${CLAUDE_SKILL_DIR}/scripts/audit.py"`.

1. **Check needs.**
2. **Audit.**
   ```
   python3 scripts/audit.py <book.xlsx> [--sheet NAME]
   ```
   The file is opened as a zip and read; it is never written.
3. **Read the findings.** A number typed where its neighbours hold formulas is the classic overwritten formula. A formula that differs from both neighbours may be a deliberate exception: ask before calling it wrong. Typed numbers inside formulas (=B4*1.18) hide assumptions; they belong in their own labelled cell.
4. **Report.** End state first. Then blocking findings by cell, warnings, then everything not read. If formulas had no saved result, say the user should open and save the file in their spreadsheet program, then audit again.

## Rules

- The script sees the values saved in the file. It does not recalculate; never claim the numbers are correct, only that no saved error was found.
- Do not change the workbook. Fixes go to the user with cell addresses.
- Limits are in `references/limits.json` and are unverified defaults.

## Not for

- Creating or editing a workbook → use the spreadsheet tool the user has; this skill only reads.
- A CSV or exported sheet → use `data-profile`.
- Tracing a report's numbers back to cells → use `number-trace`.

## Level

- beginner: explain each kind of finding with one of the cells it names.
- standard: as written.
- expert: findings by cell and the RESULT line. Every check still runs.

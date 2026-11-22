# Plan: date header parsing

Goal: Reports show the date from the file header in ISO form.
Spec: docs/spec.md

## Task 1: Parse the date header

Files: src/dates.py, tests/test_dates.py (new)
Uses: read_header
Makes: parse_date, DateError
Check: `python3 -m unittest tests.test_dates -v`
Expect: Ran 2 tests, OK

1. Add `parse_date(text)` to src/dates.py. It returns a `datetime.date` or raises `DateError`.
2. Cover one valid header and one header with no date.

## Task 2: Show the date in the report

Files:
- src/report.py
- tests/test_report.py (new)
Uses: parse_date
Makes: report_line
Check: `python3 -m unittest tests.test_report -v`
Expect: Ran 1 test, OK

1. `report_line(header)` calls `parse_date` and prints the date as YYYY-MM-DD.

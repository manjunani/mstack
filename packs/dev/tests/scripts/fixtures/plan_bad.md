# Plan: date header parsing

Goal: Reports show the date.
Spec: docs/missing-spec.md

## Task 1: Parse the date header

Files: src/dates.py, src/nowhere.py
Uses: read_headers
Makes: parse_date
Check: `python3 -m unittest tests.test_dates -v`
Expect: works

1. Add `parseDate` and handle edge cases.
2. TODO decide the error type.

## Task 3: Show the date in the report

Files: various
Uses: format_day, parse-date
Check: manual
Expect: Ran 1 test, OK

1. Similar to above, add error handling as needed.

## Task 4: Add the formatter

Makes: format_day
Expect: 2 passed

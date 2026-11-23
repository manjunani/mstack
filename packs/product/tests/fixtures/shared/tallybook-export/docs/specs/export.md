# Spec: CSV export of the reports page

## Goal

Robin and Ines, the two accountants, copy ledger rows from the reports page into a spreadsheet by
hand for every client at month end. A "Download CSV" button on the reports page gives them the rows
they are looking at as a file instead. We want it live before the November close on 2026-12-01, and
we expect it to save each of them about two hours a month. It is built in `tallybook/web.py` with
the standard library only, by one developer in one week.

## Done when

- R-001: With a client and a month filtered, the downloaded file holds the same rows in the same order as the table on screen. Check: test: tests/test_export.py::test_same_rows_as_screen
- R-002: The file is named reports-YYYY-MM-DD.csv with the download date. Check: test: tests/test_export.py::test_file_name
- R-003: The first line of the file is the header date,client,account,amount,note. Check: test: tests/test_export.py::test_header
- R-004: When the filter matches no rows the button is disabled. Check: inspect: open /reports?client=Nobody and see the greyed-out button
- R-005: Amounts are written with a dot and two decimals, as the accountants' spreadsheet expects. Check: test: tests/test_export.py::test_amount_format

## Not doing

- Excel files.
- Scheduled or emailed exports.
- Exporting every client at once.

## Open questions

- none

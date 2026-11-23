# Spec: reports page and password reset

## Goal

The accounting team sees each client's ledger rows on the reports page for the month-end check,
and a team member who forgot a password can set a new one without asking an admin.

## Done when

- R-001: Filtering by client and month shows only that client's rows for that month. Check: test: tests/test_ledger.py
- R-002: Report rows are listed oldest first. Check: test: tests/test_ledger.py
- R-003: The line under the table shows the sum of the amounts shown. Check: test: tests/test_ledger.py
- R-004: A reset link stops working 30 minutes after it was sent. Check: test: tests/test_accounts.py

## Not doing

- Editing ledger rows from the reports page.

## Open questions

- none

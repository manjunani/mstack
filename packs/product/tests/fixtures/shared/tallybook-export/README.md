# Tallybook

A small internal app for our accounting team. It keeps the ledger rows of each client and shows
them on the reports page, where the team filters by client and month before the month-end check.

Run it:

    python3 -m tallybook.cli reports --client "Harbor Bakery" --month 2026-10
    python3 -m tallybook.web            # serves the reports page on http://127.0.0.1:8040/reports

Tests:

    python3 -m unittest discover -s tests

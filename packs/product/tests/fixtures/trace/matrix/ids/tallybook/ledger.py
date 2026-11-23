"""Read ledger rows and filter them the way the reports page does."""
import csv
import pathlib

DATA = pathlib.Path(__file__).resolve().parent.parent / "data" / "ledger.csv"


def load_rows(path=DATA):
    with open(path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["amount"] = round(float(row["amount"]), 2)
    return rows


def filter_rows(rows, client=None, month=None):  # R-001, R-002
    """Rows for one client and/or one month (YYYY-MM), oldest first, then by entry id."""
    picked = [r for r in rows
              if (client is None or r["client"] == client)
              and (month is None or r["date"].startswith(month))]
    return sorted(picked, key=lambda r: (r["date"], int(r["id"])))


def total(rows):
    return round(sum(r["amount"] for r in rows), 2)

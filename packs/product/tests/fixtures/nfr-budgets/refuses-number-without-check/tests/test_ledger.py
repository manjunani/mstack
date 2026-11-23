import unittest

from tallybook import ledger


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.rows = ledger.load_rows()

    def test_filter_by_client_and_month(self):
        rows = ledger.filter_rows(self.rows, client="Harbor Bakery", month="2026-10")
        self.assertEqual([r["id"] for r in rows], ["1", "3"])

    def test_rows_are_oldest_first(self):
        dates = [r["date"] for r in ledger.filter_rows(self.rows)]
        self.assertEqual(dates, sorted(dates))

    def test_total(self):
        rows = ledger.filter_rows(self.rows, client="Harbor Bakery", month="2026-10")
        self.assertEqual(ledger.total(rows), 928.30)


if __name__ == "__main__":
    unittest.main()

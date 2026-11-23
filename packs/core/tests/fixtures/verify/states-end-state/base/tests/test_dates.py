import datetime
import unittest

from src.dates import parse_day


class ParseDayTest(unittest.TestCase):
    def test_iso(self):
        self.assertEqual(parse_day("2026-03-09"), datetime.date(2026, 3, 9))

    def test_day_first(self):
        self.assertEqual(parse_day("09/03/2026"), datetime.date(2026, 3, 9))

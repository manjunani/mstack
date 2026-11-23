import datetime
import unittest

from src.bookings import nights


class NightsTest(unittest.TestCase):
    def test_two(self):
        self.assertEqual(nights(datetime.date(2026, 5, 1), datetime.date(2026, 5, 3)), 2)

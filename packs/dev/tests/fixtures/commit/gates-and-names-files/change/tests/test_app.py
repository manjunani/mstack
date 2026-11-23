import unittest

from src.app import price_with_tax


class PriceTest(unittest.TestCase):
    def test_default_rate(self):
        self.assertEqual(price_with_tax(10), 12.0)

    def test_negative_refused(self):
        with self.assertRaises(ValueError):
            price_with_tax(-1)

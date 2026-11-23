import unittest
from decimal import Decimal

from src.invoice import total


class TotalTest(unittest.TestCase):
    def test_rounds_half_up(self):
        self.assertEqual(total([{"qty": 3, "price": 0.335}]), Decimal("1.01"))


if __name__ == "__main__":
    unittest.main()

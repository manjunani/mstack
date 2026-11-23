import sys
import unittest

sys.path.insert(0, "src")
from prices import to_cents  # noqa: E402


class ToCentsTest(unittest.TestCase):
    def test_whole(self):
        self.assertEqual(to_cents(4), 400)

    def test_fraction(self):
        self.assertEqual(to_cents(19.99), 1999)


if __name__ == "__main__":
    unittest.main()

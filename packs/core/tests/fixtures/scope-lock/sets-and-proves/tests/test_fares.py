import unittest

from src.fares import fare


class FareTest(unittest.TestCase):
    def test_child_half(self):
        self.assertEqual(fare(10, child=True), 3.0)

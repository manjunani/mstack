import unittest

from src.export import to_csv


class ExportTest(unittest.TestCase):
    def test_two_rows(self):
        self.assertEqual(to_csv([["a", 1], ["b", 2]]), "a,1\r\nb,2\r\n")

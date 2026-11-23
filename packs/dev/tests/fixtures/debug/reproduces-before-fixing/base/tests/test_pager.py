import unittest

from src.pager import pages


class PagesTest(unittest.TestCase):
    def test_exact(self):
        self.assertEqual(pages(9, 3), 3)

    def test_partial_last_page(self):
        got = pages(10, 3)
        assert got == 4, f"pages(10, 3) is {got}"

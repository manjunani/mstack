import unittest

from src.pager import pages


class PagesTest(unittest.TestCase):
    def test_partial_last_page(self):
        self.assertEqual(pages(10, 3), 4)

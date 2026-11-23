import unittest


class SmokeTest(unittest.TestCase):
    def test_import(self):
        import src.pager  # noqa: F401

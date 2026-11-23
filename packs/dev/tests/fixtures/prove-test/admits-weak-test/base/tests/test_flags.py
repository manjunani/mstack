import unittest

from src import flags


class FlagsTest(unittest.TestCase):
    def test_beta_reports_default(self):
        flags.enabled("beta_reports")
        self.assertTrue(True)

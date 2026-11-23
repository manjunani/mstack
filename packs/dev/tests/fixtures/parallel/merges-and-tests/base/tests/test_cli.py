import contextlib
import io
import unittest

from src.cli import main


class CliTest(unittest.TestCase):
    def test_berth(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main(["B2"])
        self.assertEqual(out.getvalue().strip(), "berth B2")

import contextlib
import io
import unittest

from src.cli import main


class StatusTest(unittest.TestCase):
    def test_text(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main(["status"])
        self.assertIn("free berths: 4", out.getvalue())

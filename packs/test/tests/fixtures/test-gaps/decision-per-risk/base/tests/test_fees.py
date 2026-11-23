import sys

sys.path.insert(0, "src")
from fees import nightly_fee  # noqa: E402


def test_short_boat():
    assert nightly_fee(8) == 24

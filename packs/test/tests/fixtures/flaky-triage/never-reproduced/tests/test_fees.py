import sys

sys.path.insert(0, "src")
from fees import nightly_fee  # noqa: E402


def test_short_boat():
    assert nightly_fee(8) == 24


def test_long_boat():
    assert nightly_fee(15) == 52.5


if __name__ == "__main__":
    test_short_boat()
    test_long_boat()
    print("ok")

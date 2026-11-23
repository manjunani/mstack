import sys
import time

sys.path.insert(0, "src")
from sync import SyncJob  # noqa: E402


def test_sync_finishes():
    job = SyncJob(["b-101", "b-102"]).start()
    time.sleep(0.03)
    assert job.finished
    assert job.sent == ["B-101", "B-102"]


if __name__ == "__main__":
    test_sync_finishes()
    print("ok")

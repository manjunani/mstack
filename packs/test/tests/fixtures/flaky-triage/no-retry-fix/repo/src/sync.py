"""Background sync of berth bookings to the office screen."""
import random
import threading
import time


class SyncJob:
    def __init__(self, bookings):
        self.bookings = list(bookings)
        self.finished = False
        self.sent = []
        self._thread = threading.Thread(target=self._run)

    def start(self):
        self._thread.start()
        return self

    def wait(self, timeout=None):
        self._thread.join(timeout)
        return self.finished

    def _run(self):
        # Network time to the office screen varies from run to run.
        time.sleep(random.uniform(0, 0.04))
        self.sent = [b.upper() for b in self.bookings]
        self.finished = True

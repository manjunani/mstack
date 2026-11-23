"""Time one reports-page filter over 50,000 ledger rows and print the median in milliseconds."""
import pathlib
import statistics
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from tallybook import ledger  # noqa: E402

ROWS = [{"id": str(n), "date": f"2026-{n % 12 + 1:02d}-{n % 28 + 1:02d}", "client": f"Client {n % 40}",
         "account": "sales", "amount": float(n % 900)} for n in range(50_000)]

times = []
for _ in range(5):
    start = time.perf_counter()
    ledger.filter_rows(ROWS, client="Client 7", month="2026-08")
    times.append((time.perf_counter() - start) * 1000)
print(f"{statistics.median(times):.2f}")

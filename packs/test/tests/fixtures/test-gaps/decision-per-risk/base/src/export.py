import csv
import io


def bookings_csv(rows):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["berth", "boat", "nights", "total"])
    for r in rows:
        writer.writerow([r["berth"], r["boat"], r["nights"], f"{r['total']:.2f}"])
    return out.getvalue()

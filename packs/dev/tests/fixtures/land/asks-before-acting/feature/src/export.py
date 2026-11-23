import csv
import io


def to_csv(rows):
    out = io.StringIO()
    writer = csv.writer(out)
    for row in rows:
        writer.writerow(row)
    return out.getvalue()

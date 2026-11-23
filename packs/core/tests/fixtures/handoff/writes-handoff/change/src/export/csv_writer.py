import csv
import io


def write_rows(rows, columns):
    """Return the rows as CSV text with a header line."""
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()

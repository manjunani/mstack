def to_lines(rows):
    return "\n".join(",".join(str(v) for v in row) for row in rows)

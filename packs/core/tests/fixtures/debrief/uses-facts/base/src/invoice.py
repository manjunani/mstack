def total(lines):
    """Sum quantity times unit price over invoice lines."""
    return sum(line["qty"] * line["price"] for line in lines)

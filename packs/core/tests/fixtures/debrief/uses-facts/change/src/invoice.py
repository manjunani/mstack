from decimal import Decimal, ROUND_HALF_UP


def total(lines):
    """Sum quantity times unit price over invoice lines, rounded to whole cents."""
    raw = sum(Decimal(str(line["qty"])) * Decimal(str(line["price"])) for line in lines)
    return raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

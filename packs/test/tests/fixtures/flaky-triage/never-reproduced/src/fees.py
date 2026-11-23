def nightly_fee(length_m):
    """3 per metre up to 10 m, 3.50 per metre above that."""
    return length_m * (3 if length_m <= 10 else 3.5)

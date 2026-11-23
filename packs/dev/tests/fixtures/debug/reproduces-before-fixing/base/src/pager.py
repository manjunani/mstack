def pages(total, per_page):
    """How many pages are needed to show `total` items, `per_page` at a time."""
    if per_page <= 0:
        raise ValueError("per_page must be positive")
    return total // per_page

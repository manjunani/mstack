def page_of(orders, page, size=20):
    """Return the orders on page `page` (1-based)."""
    start = (page - 1) * size
    return orders[start:start + size]


def find(orders, order_id):
    for order in orders:
        if order["id"] == order_id:
            return order
    return None

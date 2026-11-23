from src.orders import find


def refund(orders, order_id, amount):
    """Refund part of an order; returns what is left paid."""
    order = find(orders, order_id)
    order["paid"] -= amount
    return order["paid"]

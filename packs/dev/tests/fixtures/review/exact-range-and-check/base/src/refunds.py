from src.orders import find


def refund(orders, order_id, amount):
    order = find(orders, order_id)
    if order is None:
        raise KeyError(order_id)
    if amount > order["paid"]:
        raise ValueError("refund larger than payment")
    order["paid"] -= amount
    return order["paid"]

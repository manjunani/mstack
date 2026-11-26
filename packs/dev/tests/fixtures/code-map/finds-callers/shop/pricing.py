"""Prices and discounts for the shop."""

MEMBER_RATE = 0.1


def apply_discount(price, code=None):
    if code == "MEMBER":
        return round(price * (1 - MEMBER_RATE), 2)
    return price


def bulk_price(prices):
    return [apply_discount(p) for p in prices]

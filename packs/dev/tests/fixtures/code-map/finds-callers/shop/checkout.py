from shop.cart import Cart
from shop import pricing


def pay(prices, code=None):
    cart = Cart()
    for p in prices:
        cart.add(p)
    # apply_discount used to be called here directly
    return cart.total(code)


def quote(price):
    return pricing.apply_discount(price, "MEMBER")

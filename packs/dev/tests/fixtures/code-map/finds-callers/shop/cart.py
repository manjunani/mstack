from shop.pricing import apply_discount


class Cart:
    def __init__(self):
        self.items = []

    def add(self, price):
        self.items.append(price)

    def total(self, code=None):
        return sum(apply_discount(p, code) for p in self.items)

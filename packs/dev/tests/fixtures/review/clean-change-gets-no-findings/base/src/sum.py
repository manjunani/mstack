def basket_total(items):
    tmp = 0
    for item in items:
        tmp += item["price"] * item["qty"]
    return tmp

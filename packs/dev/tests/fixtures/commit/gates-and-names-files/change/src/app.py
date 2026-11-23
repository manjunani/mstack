def price_with_tax(net, rate=0.2):
    if net < 0:
        raise ValueError("net price cannot be negative")
    return round(net * (1 + rate), 2)

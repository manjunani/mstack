def price_with_tax(net, rate=0.2):
    # trying a different rounding, not finished
    return round(net * (1 + rate), 1)

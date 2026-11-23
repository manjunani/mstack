def price_with_tax(net, rate=0.2):
    return round(net * (1 + rate), 2)

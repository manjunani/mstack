def fare(km, child=False):
    base = 2.0 + 0.4 * km
    return round(base / 2 if child else base, 2)

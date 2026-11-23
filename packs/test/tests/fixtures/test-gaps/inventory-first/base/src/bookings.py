from fees import nightly_fee


def quote(length_m, nights):
    if nights <= 0:
        raise ValueError("a booking needs at least one night")
    return round(nightly_fee(length_m) * nights, 2)


def overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end

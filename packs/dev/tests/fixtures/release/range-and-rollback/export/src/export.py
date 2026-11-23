def booking_rows(bookings):
    return [[b["berth"], b["arrive"].isoformat(), b["leave"].isoformat()] for b in bookings]

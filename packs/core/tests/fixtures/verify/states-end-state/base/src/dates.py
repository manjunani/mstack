import datetime


def parse_day(text):
    """Parse '2026-03-09' or '09/03/2026' (day first) into a date."""
    text = text.strip()
    if "-" in text:
        return datetime.date.fromisoformat(text)
    day, month, year = text.split("/")
    return datetime.date(int(year), int(month), int(day))

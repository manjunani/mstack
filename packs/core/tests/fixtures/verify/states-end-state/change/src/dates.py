import datetime


def parse_day(text):
    """Parse '2026-03-09' or '03/09/2026' into a date."""
    text = text.strip()
    if "-" in text:
        return datetime.date.fromisoformat(text)
    month, day, year = text.split("/")
    return datetime.date(int(year), int(month), int(day))

def render_total(amount, currency="EUR"):
    return f"{amount:.2f} {currency}"


def format_line(name, amount):
    return f"{name}: {render_total(amount)}"

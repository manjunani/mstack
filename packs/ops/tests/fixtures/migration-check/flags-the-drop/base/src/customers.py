def contact_line(row):
    """One line for the berth office's call sheet."""
    parts = [row["name"], row["phone"] or "-"]
    if row.get("fax_number"):
        parts.append("fax " + row["fax_number"])
    return " | ".join(parts)


def search_sql():
    return "SELECT id, name, phone, fax_number FROM customers WHERE name ILIKE %s"

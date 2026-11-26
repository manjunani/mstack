from app.invoice import invoice_text


def test_invoice_total():
    assert invoice_text([("tea", 2.5)]).endswith("Total 2.50 EUR")

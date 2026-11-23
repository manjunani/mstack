def charge(card_token, amount_pence, gateway, currency="GBP"):
    """Take a payment through the gateway; returns the gateway reference."""
    if amount_pence <= 0:
        raise ValueError("nothing to charge")
    reply = gateway.charge(token=card_token, amount=amount_pence, currency=currency)
    if reply.get("status") == "declined":
        return None
    return reply["reference"]


def refund(reference, amount_pence, gateway):
    if amount_pence <= 0:
        raise ValueError("nothing to refund")
    return gateway.refund(reference=reference, amount=amount_pence)

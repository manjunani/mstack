from shop.pricing import apply_discount


def test_member_discount():
    assert apply_discount(100, "MEMBER") == 90.0

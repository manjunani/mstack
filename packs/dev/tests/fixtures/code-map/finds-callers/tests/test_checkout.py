from shop.checkout import pay


def test_pay_without_code():
    assert pay([10, 20]) == 30

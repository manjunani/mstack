import unittest

from src.forms.signup import handle_signup


class SignupTest(unittest.TestCase):
    def test_stores(self):
        store = []
        handle_signup({"email": "sam@example.test", "name": "Sam"}, store)
        self.assertEqual(len(store), 1)

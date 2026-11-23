import datetime
import unittest

from tallybook import accounts


class ResetTests(unittest.TestCase):
    def test_unknown_address_gets_no_link(self):
        self.assertIsNone(accounts.request_reset("nobody@tallybook.test", {}))

    def test_short_password_is_refused(self):
        users = {"robin@tallybook.test": "old"}
        link = accounts.request_reset("robin@tallybook.test", users)
        with self.assertRaises(ValueError):
            accounts.reset_password(link.split("=", 1)[1], "short", users)

    def test_expired_link_is_refused(self):
        users = {"robin@tallybook.test": "old"}
        start = datetime.datetime(2026, 11, 1, 9, 0, tzinfo=datetime.timezone.utc)
        link = accounts.request_reset("robin@tallybook.test", users, now=start)
        later = start + datetime.timedelta(minutes=31)
        with self.assertRaises(ValueError):
            accounts.reset_password(link.split("=", 1)[1], "long enough pass", users, now=later)


if __name__ == "__main__":
    unittest.main()

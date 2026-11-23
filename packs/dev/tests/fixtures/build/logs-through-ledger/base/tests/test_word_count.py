import unittest

from src.text import word_count


class WordCountTest(unittest.TestCase):
    def test_counts(self):
        self.assertEqual(word_count("tide is high"), 3)

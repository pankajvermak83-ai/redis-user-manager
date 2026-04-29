import unittest
from unittest.mock import patch
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import tests.conftest  # noqa: F401

from user_manager.exceptions import UserManagerError
from user_manager import id_generator


class TestMakePrefix(unittest.TestCase):
    def test_basic(self):           self.assertEqual(id_generator.make_prefix("Alice"),    "AL")
    def test_lowercase(self):       self.assertEqual(id_generator.make_prefix("bob"),      "BO")
    def test_skips_digits(self):    self.assertEqual(id_generator.make_prefix("3 Alice"),  "AL")
    def test_skips_accented(self):  self.assertEqual(id_generator.make_prefix("Ångström"), "NG")
    def test_punctuation(self):     self.assertEqual(id_generator.make_prefix("O'Brien"),  "OB")

    def test_too_short_raises(self):
        with self.assertRaises(ValueError): id_generator.make_prefix("A")

    def test_empty_raises(self):
        with self.assertRaises(ValueError): id_generator.make_prefix("")

    def test_no_ascii_letters_raises(self):
        with self.assertRaises(ValueError): id_generator.make_prefix("123")


class TestClaimUniqueId(unittest.TestCase):
    def _make_store(self, existing=None):
        existing = set(existing or [])
        return (
            lambda uid: uid in existing,
            existing.add,
        )

    def test_returns_formatted_id(self):
        contains, add = self._make_store()
        uid = id_generator.claim_unique_id("AL", contains, add)
        self.assertRegex(uid, r"^AL\d{5}$")

    def test_zero_padding(self):
        contains, add = self._make_store()
        with patch("secrets.randbelow", return_value=7):
            uid = id_generator.claim_unique_id("DA", contains, add)
        self.assertEqual(uid, "DA00007")

    def test_retries_on_collision(self):
        existing = {"AL00001", "AL00002", "AL00003"}
        contains, add = self._make_store(existing)
        numbers = iter([1, 2, 3, 42])
        with patch("secrets.randbelow", side_effect=numbers):
            uid = id_generator.claim_unique_id("AL", contains, add)
        self.assertEqual(uid, "AL00042")

    def test_exhausted_raises(self):
        # Every candidate is already taken
        taken = set()
        def always_taken(uid):
            taken.add(uid)
            return True
        with self.assertRaises(UserManagerError):
            id_generator.claim_unique_id("AL", always_taken, lambda _: None)


if __name__ == "__main__":
    unittest.main(verbosity=2)

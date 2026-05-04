import unittest
from unittest.mock import MagicMock, patch
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import test1.conftest  # noqa: F401
from test1.conftest import FakeRedisError, FakeConnectionError

from user_manager.service import UserManager
from user_manager.exceptions import UserAlreadyExistsException, UserManagerError


def make_manager():
    client = MagicMock()
    mgr = UserManager(client=client)
    return mgr, client


def make_pipe(client, results=None):
    pipe = MagicMock()
    pipe.execute.return_value = results or []
    client.pipeline.return_value = pipe
    return pipe


class TestConstruction(unittest.TestCase):
    def test_ping_on_init(self):
        client = MagicMock()
        UserManager(client=client)
        client.ping.assert_called_once()

    def test_connection_error_wraps(self):
        client = MagicMock()
        client.ping.side_effect = FakeConnectionError("refused")
        with self.assertRaises(ConnectionError):
            UserManager(client=client)


class TestAddUser(unittest.TestCase):
    def setUp(self):
        self.mgr, self.client = make_manager()

    def _setup_happy(self):
        # name sadd → new; id sismember → not taken; id sadd → ok
        self.client.sadd.return_value = 1
        self.client.sismember.return_value = False
        make_pipe(self.client)

    def test_returns_prefixed_id(self):
        self._setup_happy()
        uid = self.mgr.add_user("Alice")
        self.assertRegex(uid, r"^AL\d{5}$")

    def test_extra_fields_stringified(self):
        self._setup_happy()
        uid = self.mgr.add_user("Alice", age=30, active=True)
        mapping = self.client.hset.call_args.kwargs["mapping"]
        self.assertEqual(mapping["age"], "30")
        self.assertEqual(mapping["active"], "True")

    def test_duplicate_raises(self):
        self.client.sadd.return_value = 0
        with self.assertRaises(UserAlreadyExistsException):
            self.mgr.add_user("Alice")

    def test_non_string_raises(self):
        with self.assertRaises(ValueError): self.mgr.add_user(99)

    def test_empty_name_raises(self):
        with self.assertRaises(ValueError): self.mgr.add_user("  ")

    def test_reserved_user_id_field_raises(self):
        with self.assertRaises(ValueError): self.mgr.add_user("Alice", user_id="x")

    def test_rollback_on_hset_failure(self):
        self.client.sadd.return_value = 1
        self.client.sismember.return_value = False
        self.client.hset.side_effect = FakeRedisError("disk full")
        make_pipe(self.client)
        with self.assertRaises(FakeRedisError):
            self.mgr.add_user("Alice")
        self.client.pipeline.assert_called()


class TestGetUserById(unittest.TestCase):
    def setUp(self):
        self.mgr, self.client = make_manager()

    def test_returns_user(self):
        self.client.hgetall.return_value = {"user_id": "AL00001", "name": "Alice"}
        self.assertEqual(self.mgr.get_user_by_id("AL00001")["name"], "Alice")

    def test_strips_whitespace(self):
        self.client.hgetall.return_value = {"user_id": "AL00001", "name": "Alice"}
        self.mgr.get_user_by_id("  AL00001  ")
        self.client.hgetall.assert_called_with("user:AL00001")

    def test_empty_raises(self):
        with self.assertRaises(ValueError): self.mgr.get_user_by_id("")

    def test_non_string_raises(self):
        with self.assertRaises(ValueError): self.mgr.get_user_by_id(123)


class TestGetAllUsers(unittest.TestCase):
    def setUp(self):
        self.mgr, self.client = make_manager()

    def test_empty(self):
        self.client.sscan_iter.return_value = iter([])
        self.assertEqual(self.mgr.get_all_users(), [])

    def test_returns_list(self):
        self.client.sscan_iter.return_value = iter(["AL00001"])
        make_pipe(self.client, [{"user_id": "AL00001", "name": "Alice"}])
        self.assertEqual(len(self.mgr.get_all_users()), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)

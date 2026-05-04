import unittest
from unittest.mock import MagicMock, patch
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import test1.conftest  # noqa: F401
from test1.conftest import FakeRedisError

from user_manager import repository
from user_manager.exceptions import UserManagerError, UserNotFoundException


def make_client():
    return MagicMock()


def make_pipe(client, results=None):
    pipe = MagicMock()
    pipe.execute.return_value = results or []
    client.pipeline.return_value = pipe
    return pipe


class TestReserveName(unittest.TestCase):
    def test_new_name_returns_true(self):
        client = make_client()
        client.sadd.return_value = 1
        self.assertTrue(repository.reserve_name(client, "Alice"))

    def test_duplicate_returns_false(self):
        client = make_client()
        client.sadd.return_value = 0
        self.assertFalse(repository.reserve_name(client, "Alice"))

    def test_redis_error_raises(self):
        client = make_client()
        client.sadd.side_effect = FakeRedisError("down")
        with self.assertRaises(UserManagerError):
            repository.reserve_name(client, "Alice")


class TestIdHelpers(unittest.TestCase):
    def test_id_exists_true(self):
        client = make_client()
        client.sismember.return_value = True
        self.assertTrue(repository.id_exists(client, "AL12345"))

    def test_id_exists_false(self):
        client = make_client()
        client.sismember.return_value = False
        self.assertFalse(repository.id_exists(client, "AL99999"))

    def test_add_user_id(self):
        client = make_client()
        repository.add_user_id(client, "AL12345")
        client.sadd.assert_called_once_with(repository.USER_IDS_KEY, "AL12345")


class TestReadUser(unittest.TestCase):
    def test_returns_data(self):
        client = make_client()
        client.hgetall.return_value = {"user_id": "AL12345", "name": "Alice"}
        data = repository.read_user(client, "AL12345")
        self.assertEqual(data["name"], "Alice")

    def test_not_found_raises(self):
        client = make_client()
        client.hgetall.return_value = {}
        with self.assertRaises(UserNotFoundException):
            repository.read_user(client, "XX99999")

    def test_redis_error_raises(self):
        client = make_client()
        client.hgetall.side_effect = FakeRedisError("gone")
        with self.assertRaises(UserManagerError):
            repository.read_user(client, "AL12345")


class TestFetchAll(unittest.TestCase):
    def test_empty(self):
        client = make_client()
        client.sscan_iter.return_value = iter([])
        self.assertEqual(repository.fetch_all(client), [])

    def test_returns_users(self):
        client = make_client()
        client.sscan_iter.return_value = iter(["AL00001"])
        make_pipe(client, [{"user_id": "AL00001", "name": "Alice"}])
        result = repository.fetch_all(client)
        self.assertEqual(len(result), 1)

    def test_deduplicates_by_name(self):
        client = make_client()
        client.sscan_iter.return_value = iter(["AL00001", "AL00002"])
        make_pipe(client, [
            {"user_id": "AL00001", "name": "Alice"},
            {"user_id": "AL00002", "name": "Alice"},
        ])
        self.assertEqual(len(repository.fetch_all(client)), 1)

    def test_skips_empty_hashes(self):
        client = make_client()
        client.sscan_iter.return_value = iter(["AL00001", "BO00002"])
        make_pipe(client, [{}, {"user_id": "BO00002", "name": "Bob"}])
        result = repository.fetch_all(client)
        self.assertEqual(result[0]["name"], "Bob")

    def test_redis_error_raises(self):
        client = make_client()
        client.sscan_iter.side_effect = FakeRedisError("timeout")
        with self.assertRaises(UserManagerError):
            repository.fetch_all(client)


class TestRollback(unittest.TestCase):
    def test_rollback_no_user_id(self):
        client = make_client()
        pipe = make_pipe(client)
        repository.rollback(client, name="Alice", user_id=None)
        pipe.srem.assert_called_once_with(repository.NAMES_KEY, "Alice")
        pipe.delete.assert_not_called()

    def test_rollback_with_user_id(self):
        client = make_client()
        pipe = make_pipe(client)
        repository.rollback(client, name="Alice", user_id="AL12345")
        pipe.srem.assert_any_call(repository.NAMES_KEY, "Alice")
        pipe.srem.assert_any_call(repository.USER_IDS_KEY, "AL12345")
        pipe.delete.assert_called_once_with(repository.user_key("AL12345"))


if __name__ == "__main__":
    unittest.main(verbosity=2)

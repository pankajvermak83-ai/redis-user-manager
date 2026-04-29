import unittest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import tests.conftest  # noqa: F401 — installs redis stub

from user_manager.exceptions import (
    UserManagerError,
    UserAlreadyExistsException,
    UserNotFoundException,
    MissingEnvironmentVariableException,
)


class TestExceptionHierarchy(unittest.TestCase):
    def test_already_exists_is_manager_error(self):
        self.assertTrue(issubclass(UserAlreadyExistsException, UserManagerError))

    def test_not_found_is_manager_error(self):
        self.assertTrue(issubclass(UserNotFoundException, UserManagerError))

    def test_missing_env_is_manager_error(self):
        self.assertTrue(issubclass(MissingEnvironmentVariableException, UserManagerError))

    def test_all_are_exceptions(self):
        for cls in (UserManagerError, UserAlreadyExistsException,
                    UserNotFoundException, MissingEnvironmentVariableException):
            self.assertTrue(issubclass(cls, Exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)

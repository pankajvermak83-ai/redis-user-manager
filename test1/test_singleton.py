import unittest
from unittest.mock import MagicMock, patch
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import tests.conftest  # noqa: F401

import user_manager.singleton as sg
from user_manager.service import UserManager


class TestSingleton(unittest.TestCase):
    def tearDown(self):
        sg.reset_user_service()

    def test_same_instance_on_repeated_calls(self):
        with patch.object(sg, "UserManager") as MockUM:
            MockUM.return_value = MagicMock()
            s1 = sg.get_user_service()
            s2 = sg.get_user_service()
            self.assertIs(s1, s2)
            MockUM.assert_called_once()

    def test_reset_forces_new_instance(self):
        with patch.object(sg, "UserManager") as MockUM:
            MockUM.return_value = MagicMock()
            sg.get_user_service()
            sg.reset_user_service()
            sg.get_user_service()
            self.assertEqual(MockUM.call_count, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from packaging.windows.launcher import SingleInstance, default_data_dir


class WindowsReleaseTests(unittest.TestCase):
    def test_launcher_uses_explicit_data_root(self):
        with patch.dict(os.environ, {"JOB_TRACKER_DATA_DIR": r"C:\\Users\\tester\\AppData\\Roaming\\Job Tracker"}):
            self.assertEqual(default_data_dir(), Path(r"C:\\Users\\tester\\AppData\\Roaming\\Job Tracker"))

    def test_single_instance_rejects_second_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "instance.lock"
            first = SingleInstance(path)
            second = SingleInstance(path)
            self.assertTrue(first.acquire())
            try:
                self.assertFalse(second.acquire())
            finally:
                first.close()
                second.close()


if __name__ == "__main__":
    unittest.main()

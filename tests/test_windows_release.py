import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from release_packaging.windows.launcher import INSTANCE_MUTEX, SingleInstance, default_data_dir
from version import normalize_semver, semver_key
from packaging.version import Version


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

    def test_inno_mutex_matches_launcher_mutex(self):
        script = Path(__file__).parents[1] / "release_packaging" / "windows" / "JobTracker.iss"
        self.assertIn(f"AppMutex={INSTANCE_MUTEX}", script.read_text(encoding="utf-8"))

    def test_semver_normalization_and_ordering(self):
        self.assertEqual(normalize_semver("v1.0.0"), "1.0.0")
        self.assertEqual(semver_key("1.0.0"), semver_key("v1.0.0"))
        self.assertGreater(semver_key("1.0.1"), semver_key("v1.0.0"))
        self.assertLess(semver_key("1.0.0-rc.1"), semver_key("1.0.0"))

    def test_third_party_packaging_namespace_is_not_shadowed(self):
        self.assertEqual(str(Version("1.2.3")), "1.2.3")


if __name__ == "__main__":
    unittest.main()

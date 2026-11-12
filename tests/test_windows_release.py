import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from release_packaging.windows.launcher import INSTANCE_MUTEX, SingleInstance, default_data_dir, stop_waitress_server
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

    def test_shutdown_closes_browser_keepalive_channels_before_waiting(self):
        server = Mock()
        server._map = {1: Mock()}
        server_thread = Mock()
        server_thread.is_alive.return_value = True
        events = []
        server.close.side_effect = lambda: events.append("server.close")
        server_thread.join.side_effect = lambda timeout: events.append("thread.join")
        with patch("waitress.wasyncore.close_all") as close_all:
            close_all.side_effect = lambda server_map: events.append("close_all")
            stop_waitress_server(server, server_thread)
        self.assertEqual(events, ["server.close", "close_all", "thread.join"])
        server.close.assert_called_once_with()
        server_thread.join.assert_called_once_with(timeout=5)
        close_all.assert_called_once_with(server._map)

    def test_waitress_exits_with_browser_keepalive_connection(self):
        from waitress import create_server

        def respond(_environ, start_response):
            start_response("200 OK", [("Content-Type", "text/plain")])
            return [b"ready"]

        server = create_server(respond, host="127.0.0.1", port=0)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            with socket.create_connection(("127.0.0.1", server.effective_port), timeout=5) as browser:
                browser.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
                self.assertIn(b"200 OK", browser.recv(4096))
                self.assertTrue(thread.is_alive())
                stop_waitress_server(server, thread)
                thread.join(timeout=3)
                self.assertFalse(thread.is_alive())
        finally:
            if thread.is_alive():
                server.close()

    def test_semver_normalization_and_ordering(self):
        self.assertEqual(normalize_semver("v1.0.0"), "1.0.0")
        self.assertEqual(semver_key("1.0.0"), semver_key("v1.0.0"))
        self.assertGreater(semver_key("1.0.1"), semver_key("v1.0.0"))
        self.assertLess(semver_key("1.0.0-rc.1"), semver_key("1.0.0"))

    def test_third_party_packaging_namespace_is_not_shadowed(self):
        self.assertEqual(str(Version("1.2.3")), "1.2.3")


if __name__ == "__main__":
    unittest.main()

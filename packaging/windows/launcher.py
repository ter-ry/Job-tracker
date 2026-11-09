"""Start Job Tracker as a local, single-instance Windows desktop app.

This module is the PyInstaller entrypoint.  It deliberately sets the data root
before importing Flask so frozen code and user data can never be confused.
"""

from __future__ import annotations

import atexit
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser


HOST = "127.0.0.1"
PORT = 5000
APPDATA_FOLDER = "Job Tracker"


def default_data_dir() -> Path:
    configured = os.environ.get("JOB_TRACKER_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    appdata = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
    if appdata:
        return Path(appdata) / APPDATA_FOLDER
    return Path.home() / APPDATA_FOLDER


class SingleInstance:
    """Cross-platform testable lock; Windows uses an advisory file lock."""

    def __init__(self, path: Path):
        self.path = path
        self.handle = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+")
        self.handle.seek(0)
        self.handle.write("Job Tracker\n")
        self.handle.flush()
        if os.name == "nt":
            import msvcrt

            try:
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                self.close()
                return False
        else:
            import fcntl

            try:
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                self.close()
                return False
        return True

    def close(self) -> None:
        if self.handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        self.handle.close()
        self.handle = None


def local_health_url() -> str:
    return f"http://{HOST}:{PORT}/api/health"


def server_is_healthy(timeout: float = 0.4) -> bool:
    try:
        with urllib.request.urlopen(local_health_url(), timeout=timeout) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def wait_for_server(timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server_is_healthy():
            return True
        time.sleep(0.15)
    return False


def launch() -> int:
    data_dir = default_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["JOB_TRACKER_DATA_DIR"] = str(data_dir)
    os.environ.setdefault("JOB_TRACKER_BIND_HOST", HOST)
    os.environ.setdefault("JOB_TRACKER_PORT", str(PORT))

    lock = SingleInstance(data_dir / "instance.lock")
    if not lock.acquire():
        if server_is_healthy():
            webbrowser.open(local_health_url().replace("/api/health", "/"))
            return 0
        return 2
    atexit.register(lock.close)

    from waitress import serve

    from app import app

    thread = threading.Thread(
        target=serve,
        args=(app,),
        kwargs={"host": HOST, "port": PORT, "threads": 8, "ident": "JobTracker"},
        daemon=True,
    )
    thread.start()
    if not wait_for_server():
        return 3
    webbrowser.open(f"http://{HOST}:{PORT}/")
    thread.join()
    return 0


if __name__ == "__main__":
    raise SystemExit(launch())

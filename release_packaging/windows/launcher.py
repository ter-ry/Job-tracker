"""Start Job Tracker as a local, single-instance Windows desktop app."""

from __future__ import annotations

import atexit
import ctypes
import os
from pathlib import Path
import threading
import time
import urllib.error
import urllib.request
import webbrowser

HOST = "127.0.0.1"
PORT = 5000
APPDATA_FOLDER = "Job Tracker"
INSTANCE_MUTEX = "JobTrackerInstance"


def default_data_dir() -> Path:
    configured = os.environ.get("JOB_TRACKER_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    appdata = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
    if appdata:
        return Path(appdata) / APPDATA_FOLDER
    return Path.home() / APPDATA_FOLDER


class SingleInstance:
    """Hold the named mutex used by Inno Setup's AppMutex setting."""

    def __init__(self, path: Path, mutex_name: str = INSTANCE_MUTEX):
        self.path = path
        self.mutex_name = mutex_name
        self.handle = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
            kernel32.CreateMutexW.restype = ctypes.c_void_p
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = kernel32.CreateMutexW(None, True, self.mutex_name)
            if not handle:
                return False
            if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
                kernel32.CloseHandle(handle)
                return False
            self.handle = (kernel32, handle)
            return True
        import fcntl

        self.handle = self.path.open("a+")
        try:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.close()
            return False
        return True

    def close(self) -> None:
        if self.handle is None:
            return
        if os.name == "nt":
            kernel32, handle = self.handle
            kernel32.CloseHandle(handle)
        else:
            import fcntl

            try:
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


def stop_waitress_server(server: object, server_thread: threading.Thread) -> None:
    # Closing the listener alone does not wake Waitress while a browser keeps
    # an accepted keep-alive connection open. Close those channels before
    # waiting, otherwise launch() can remain blocked on the server thread.
    server.close()
    from waitress import wasyncore

    wasyncore.close_all(server._map)
    server_thread.join(timeout=5)


def launch() -> int:
    data_dir = default_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["JOB_TRACKER_DATA_DIR"] = str(data_dir)
    os.environ.setdefault("JOB_TRACKER_BIND_HOST", HOST)
    os.environ.setdefault("JOB_TRACKER_PORT", str(PORT))
    os.environ.setdefault("JOB_TRACKER_EXIT_TOKEN", os.urandom(32).hex())

    lock = SingleInstance(data_dir / "instance.lock")
    if not lock.acquire():
        if server_is_healthy():
            webbrowser.open(f"http://{HOST}:{PORT}/")
            return 0
        return 2
    atexit.register(lock.close)

    from waitress import create_server
    from app import app

    server = create_server(app, host=HOST, port=PORT, threads=8, ident="JobTracker")
    server_thread = threading.Thread(
        target=server.run,
        daemon=True,
    )

    app.config["JOB_TRACKER_SHUTDOWN"] = lambda: stop_waitress_server(server, server_thread)
    server_thread.start()
    if not wait_for_server():
        return 3
    webbrowser.open(f"http://{HOST}:{PORT}/")
    server_thread.join()
    server.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(launch())

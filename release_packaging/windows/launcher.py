"""Start Job Tracker as a local, single-instance Windows desktop app."""

from __future__ import annotations

import atexit
import ctypes
import json
import multiprocessing
import os
from pathlib import Path
import threading
import sys
import time
import urllib.error
import urllib.request
import webbrowser

HOST = "127.0.0.1"
PORT = 5000
QA_PORT = 5001
FRESH_QA_PORT = 5002
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


def canonical_data_dir() -> Path:
    """Return the owner-facing production root, independent of stale overrides."""
    appdata = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
    return (Path(appdata) / APPDATA_FOLDER) if appdata else (Path.home() / APPDATA_FOLDER)


def validated_runtime_data_dir(qa_mode: bool, fresh_qa: bool = False) -> Path | None:
    """Reject inherited data-root overrides that cross production/QA modes."""
    expected = canonical_data_dir() / ("Fresh QA Session" if fresh_qa else "QA Session") if qa_mode else canonical_data_dir()
    configured = os.environ.get("JOB_TRACKER_DATA_DIR")
    # Packaging smoke tests explicitly mark their disposable temporary root.
    # An arbitrary override is never accepted by an ordinary owner launch.
    if configured and os.environ.get("JOB_TRACKER_TEST_MODE") == "1":
        return Path(configured).expanduser()
    if configured and Path(configured).expanduser().resolve() != expected.resolve():
        return None
    return expected


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


def local_health_url(port: int = PORT) -> str:
    return f"http://{HOST}:{port}/api/health"


def server_is_healthy(timeout: float = 0.4, port: int = PORT, qa_mode: bool | None = None) -> bool:
    try:
        with urllib.request.urlopen(local_health_url(port), timeout=timeout) as response:
            if response.status != 200:
                return False
        if qa_mode is None:
            return True
        with urllib.request.urlopen(f"http://{HOST}:{port}/api/qa/status", timeout=timeout) as response:
            status = json.loads(response.read().decode("utf-8"))
        return bool(status.get("active")) == qa_mode
    except (OSError, urllib.error.URLError):
        return False


def wait_for_server(timeout: float = 30.0, port: int = PORT, qa_mode: bool | None = None) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server_is_healthy(port=port, qa_mode=qa_mode):
            return True
        time.sleep(0.15)
    return False


def open_browser_or_report(url: str, data_dir: Path) -> bool:
    """Open the app when possible and leave an actionable fallback when not."""
    try:
        opened = bool(webbrowser.open(url, new=1))
    except Exception as exc:  # browser registration can fail on locked-down Windows hosts
        opened = False
        error = f"Automatic browser launch failed: {exc}"
    else:
        error = "Automatic browser launch returned no success status."
    if opened:
        return True
    status = data_dir / "startup-status.txt"
    status.write_text(
        "Job Tracker is running, but the browser did not open automatically.\n"
        f"Open this address manually: {url}\n{error}\n",
        encoding="utf-8",
    )
    show_startup_recovery(url)
    print(f"Job Tracker is ready at {url}. Automatic browser launch failed; open the address manually.")
    return False


def show_startup_recovery(url: str) -> None:
    """Show a visible recovery prompt when the browser cannot be opened."""
    if os.name != "nt":
        return
    try:
        ctypes.windll.user32.MessageBoxW(None, f"Job Tracker is running. Open this address manually:\n\n{url}", "Job Tracker browser startup", 0x40)
    except Exception:
        return


def stop_waitress_server(server: object, server_thread: threading.Thread) -> None:
    # Closing the listener alone does not wake Waitress while a browser keeps
    # an accepted keep-alive connection open. Close those channels before
    # waiting, otherwise launch() can remain blocked on the server thread.
    try:
        server.close()
        from waitress import wasyncore

        wasyncore.close_all(server._map)
        server_thread.join(timeout=5)
    finally:
        # The authenticated exit request is the frozen application's process
        # boundary.  A Windows Waitress worker can retain a native handle even
        # after the listener and thread have been closed, so always terminate
        # the packaged process after bounded cleanup.  This also guarantees the
        # smoke and installer lifecycle gates cannot hang on a half-shutdown
        # executable.
        if getattr(sys, "frozen", False):
            os._exit(0)


def launch() -> int:
    # Required before any isolated JobSpy child is spawned from the frozen
    # launcher. The provider runtime uses Windows spawn and never re-enters
    # launch() recursively.
    multiprocessing.freeze_support()
    fresh_qa = "--fresh-qa" in sys.argv
    qa_mode = "--qa" in sys.argv or fresh_qa
    if ("--qa" in sys.argv or fresh_qa) and "--production" in sys.argv:
        show_startup_recovery("Choose either Production (port 5000) or QA (port 5001), not both.")
        return 2
    if not qa_mode and os.environ.get("JOB_TRACKER_QA_MODE") == "1":
        show_startup_recovery("Production launch refused: inherited QA mode was detected. Close this process and launch Production explicitly.")
        return 2
    runtime_port = FRESH_QA_PORT if fresh_qa else QA_PORT if qa_mode else PORT
    data_dir = validated_runtime_data_dir(qa_mode, fresh_qa)
    if data_dir is None:
        show_startup_recovery("Job Tracker launch refused: JOB_TRACKER_DATA_DIR does not match this mode's safe data directory.")
        return 2
    if qa_mode:
        os.environ["JOB_TRACKER_QA_MODE"] = "1"
        if fresh_qa:
            os.environ["JOB_TRACKER_FRESH_QA_MODE"] = "1"
        else:
            os.environ.pop("JOB_TRACKER_FRESH_QA_MODE", None)
    else:
        os.environ.pop("JOB_TRACKER_QA_MODE", None)
        os.environ.pop("JOB_TRACKER_FRESH_QA_MODE", None)
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["JOB_TRACKER_DATA_DIR"] = str(data_dir)
    os.environ.setdefault("JOB_TRACKER_BIND_HOST", HOST)
    os.environ["JOB_TRACKER_PORT"] = str(runtime_port)
    os.environ.setdefault("JOB_TRACKER_EXIT_TOKEN", os.urandom(32).hex())

    mutex_name = f"{INSTANCE_MUTEX}-FRESH-QA" if fresh_qa else f"{INSTANCE_MUTEX}-QA" if qa_mode else INSTANCE_MUTEX
    lock = SingleInstance(data_dir / "instance.lock", mutex_name=mutex_name)
    if not lock.acquire():
        if server_is_healthy(port=runtime_port, qa_mode=qa_mode):
            open_browser_or_report(f"http://{HOST}:{runtime_port}/", data_dir)
            return 0
        if qa_mode:
            show_startup_recovery(f"Disposable mode could not start because port {runtime_port} or its instance is already in use. Production was not opened.")
        return 2
    atexit.register(lock.close)

    from waitress import create_server
    from app import app

    server = create_server(app, host=HOST, port=runtime_port, threads=8, ident="JobTracker-Fresh-QA" if fresh_qa else "JobTracker-QA" if qa_mode else "JobTracker")
    server_thread = threading.Thread(
        target=server.run,
        daemon=True,
    )

    app.config["JOB_TRACKER_SHUTDOWN"] = lambda: stop_waitress_server(server, server_thread)
    server_thread.start()
    if not wait_for_server(port=runtime_port, qa_mode=qa_mode):
        show_startup_recovery(f"Job Tracker server readiness failed on http://{HOST}:{runtime_port}/")
        return 3
    open_browser_or_report(f"http://{HOST}:{runtime_port}/", data_dir)
    server_thread.join()
    server.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(launch())

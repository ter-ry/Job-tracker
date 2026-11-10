"""Launch the frozen Windows executable against disposable local data."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request


def get(url: str) -> tuple[int, bytes]:
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.status, response.read()


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: frozen_windows_smoke_test.py <frozen-executable>")
    executable = Path(sys.argv[1]).resolve()
    if not executable.is_file():
        raise SystemExit(f"Frozen executable not found: {executable}")
    with tempfile.TemporaryDirectory(prefix="job-tracker-frozen-smoke-") as data_root:
        env = os.environ.copy()
        env["JOB_TRACKER_DATA_DIR"] = data_root
        env["JOB_TRACKER_VERSION"] = "0.0.0-frozen-smoke"
        process = subprocess.Popen([str(executable)], env=env, cwd=str(executable.parent))
        base = "http://127.0.0.1:5000"
        deadline = time.monotonic() + 45
        try:
            while time.monotonic() < deadline:
                try:
                    status, _ = get(f"{base}/api/health")
                    if status == 200:
                        break
                except OSError:
                    time.sleep(0.25)
            else:
                raise AssertionError("Frozen executable did not serve /api/health within 45 seconds")

            version_status, version_body = get(f"{base}/api/version")
            index_status, index_body = get(f"{base}/")
            static_status, static_body = get(f"{base}/static/app.js")
            assert version_status == 200 and json.loads(version_body)["version"] == "0.0.0-frozen-smoke"
            assert index_status == 200 and b"Job Tracker" in index_body
            assert static_status == 200 and b"function" in static_body
            assert Path(data_root, "jobs.sqlite").is_file(), "Frozen app did not create isolated SQLite data"
            print(json.dumps({"health": 200, "version": 200, "index": len(index_body), "static": len(static_body), "data_root": data_root}))
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
            if process.poll() is None:
                raise AssertionError("Frozen executable did not shut down")


if __name__ == "__main__":
    main()

"""Disposable Windows packaging smoke test; never uses the user's database."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    with tempfile.TemporaryDirectory(prefix="job-tracker-release-smoke-") as temp:
        os.environ["JOB_TRACKER_DATA_DIR"] = temp
        os.environ["JOB_TRACKER_VERSION"] = "0.0.0-smoke"
        import app

        with app.app.test_client() as client:
            version = client.get("/api/version")
            health = client.get("/api/health")
            assert version.status_code == 200, version.text
            assert version.get_json()["version"] == "0.0.0-smoke"
            assert health.status_code == 200, health.text
            assert Path(temp, "jobs.sqlite").exists()
        print("Windows smoke test passed with isolated data root:", temp)


if __name__ == "__main__":
    main()

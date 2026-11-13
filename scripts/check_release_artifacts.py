"""Check that a release build contains an executable but no user data."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) not in {2, 3}:
        raise SystemExit("usage: check_release_artifacts.py <installer> [<bundle-directory>]")
    installer = Path(sys.argv[1])
    if not installer.is_file() or installer.stat().st_size < 1_000_000:
        raise SystemExit(f"installer missing or unexpectedly small: {installer}")
    dist = Path(sys.argv[2]) if len(sys.argv) == 3 else installer.parent / "JobTracker"
    if not (dist / "JobTracker.exe").is_file():
        raise SystemExit("PyInstaller executable is missing from the staging directory")
    forbidden = [path for path in dist.rglob("*") if path.name in {"jobs.sqlite", "instance.lock"}]
    if forbidden:
        raise SystemExit(f"user data was packaged: {forbidden}")
    print(f"Release artifact check passed: {installer} ({installer.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

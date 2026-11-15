"""Small process entry point for hard-bounded JobSpy acquisition.

The worker accepts only plain dictionaries so it can run under Windows spawn
and from a PyInstaller frozen executable. It never contains application state.
"""

from __future__ import annotations

from typing import Any


def _records(frame: Any) -> list[dict[str, Any]]:
    if frame is None:
        return []
    if hasattr(frame, "to_dict"):
        try:
            return [item for item in frame.to_dict("records") if isinstance(item, dict)]
        except Exception:
            return []
    if isinstance(frame, list):
        return [item for item in frame if isinstance(item, dict)]
    return []


def run_scrape_worker(request: dict[str, Any], result_queue: Any) -> None:
    """Run one real JobSpy call and put only serializable result data on queue."""
    try:
        from jobspy import scrape_jobs

        frame = scrape_jobs(**request)
        result_queue.put({
            "ok": True,
            "frame_type": type(frame).__name__ if frame is not None else "NoneType",
            "rows": _records(frame),
        })
    except BaseException as exc:  # child must report provider failures, including import errors
        try:
            result_queue.put({
                "ok": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
            })
        except Exception:
            pass

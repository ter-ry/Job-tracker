"""Frozen Windows probe for the bounded provider child-process runtime.

This has no network dependency.  It verifies the two properties packaging can
reliably prove: a frozen executable can spawn the provider child without
recursively relaunching itself, and a timed-out child is terminated and reaped.
"""

from __future__ import annotations

import multiprocessing
import time

from sources.provider_runtime import run_isolated_provider


def probe_worker(request, result_queue):
    if request.get("sleep"):
        time.sleep(5)
        return
    result_queue.put({"ok": True, "rows": [], "frame_type": "list"})


def main() -> None:
    multiprocessing.freeze_support()
    result = run_isolated_provider({}, 5, worker_target=probe_worker)
    assert result.get("ok") is True
    try:
        run_isolated_provider({"sleep": True}, 0.2, worker_target=probe_worker)
    except TimeoutError:
        pass
    else:
        raise AssertionError("frozen provider child did not time out")
    if any(child.name == "jobspy-provider" for child in multiprocessing.active_children()):
        raise AssertionError("frozen provider child was not reaped")
    print("Frozen provider-runtime probe passed")


if __name__ == "__main__":
    main()

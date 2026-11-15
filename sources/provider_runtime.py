"""Reusable bounded runtime helpers for provider and geocoding integration."""

from __future__ import annotations

import multiprocessing
import os
import queue
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable


class ProviderWorkerError(RuntimeError):
    def __init__(self, error_type: str, message: str):
        self.error_type = error_type
        super().__init__(message)


@dataclass
class ProviderCircuitBreaker:
    """Caller-owned breaker so failures do not hammer a source on continuation."""

    failure_threshold: int = 2
    cooldown_seconds: float = 60.0
    _failures: dict[str, int] = field(default_factory=dict)
    _opened_at: dict[str, float] = field(default_factory=dict)

    def allow(self, source: str) -> bool:
        opened = self._opened_at.get(source)
        if opened is None:
            return True
        if time.monotonic() - opened >= self.cooldown_seconds:
            self._opened_at.pop(source, None)
            self._failures.pop(source, None)
            return True
        return False

    def record(self, source: str, state: str) -> None:
        if state in {"working", "no_results"}:
            self._failures.pop(source, None)
            self._opened_at.pop(source, None)
            return
        if state in {"blocked", "timed_out", "unavailable", "unsupported", "failed"}:
            failures = self._failures.get(source, 0) + 1
            self._failures[source] = failures
            if failures >= max(1, self.failure_threshold):
                self._opened_at[source] = time.monotonic()


def multiprocessing_context() -> multiprocessing.context.BaseContext:
    """Use spawn on Windows/frozen builds and fork only for ordinary POSIX runs."""
    method = "spawn" if sys.platform == "win32" or getattr(sys, "frozen", False) else "fork"
    return multiprocessing.get_context(method)


def run_isolated_provider(
    request: dict[str, Any],
    timeout_seconds: float,
    *,
    worker_target: Callable[..., None] | None = None,
) -> dict[str, Any]:
    """Run a provider in a killable child and return its plain result payload."""
    from sources.jobspy_worker import run_scrape_worker

    multiprocessing.freeze_support()
    context = multiprocessing_context()
    result_queue = context.Queue(maxsize=1)
    process = context.Process(target=worker_target or run_scrape_worker, args=(request, result_queue), name="jobspy-provider")
    process.daemon = True
    process.start()
    deadline = time.monotonic() + max(float(timeout_seconds), 0.01)
    try:
        remaining = max(0.01, deadline - time.monotonic())
        try:
            result = result_queue.get(timeout=remaining)
        except queue.Empty as exc:
            if process.is_alive():
                process.terminate()
            process.join(timeout=2)
            if process.is_alive():
                # A provider child that ignores terminate is still reaped as
                # far as the platform permits; expose this fact to diagnostics.
                process.kill()
                process.join(timeout=2)
            raise TimeoutError(f"provider process timed out after {timeout_seconds}s") from exc
        process.join(timeout=2)
        if not result.get("ok"):
            raise ProviderWorkerError(str(result.get("error_type") or "ProviderError"), str(result.get("error") or "provider failed"))
        result["pid"] = process.pid
        result["terminated"] = False
        return result
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=2)
        result_queue.close()
        result_queue.join_thread()


def normalized_location_key(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())


@dataclass
class GeocodeRuntime:
    """Per-search geocode cache with remote skipping and query deduplication."""

    provider_name: str = ""
    timeout_seconds: float = 8.0

    def __post_init__(self) -> None:
        self._cache: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._calls = 0

    @property
    def calls(self) -> int:
        return self._calls

    def resolve(
        self,
        query: str,
        *,
        lookup_type: str = "job",
        provider: Callable[..., dict[str, Any]],
        remote: bool = False,
        context_key: str = "",
    ) -> dict[str, Any]:
        if remote:
            return {"ok": True, "status": "skipped_remote", "cached": False, "query": query}
        normalized = normalized_location_key(query)
        key = (lookup_type, normalized, normalized_location_key(context_key or self.provider_name))
        if key in self._cache:
            return {**self._cache[key], "cached": True}
        self._calls += 1
        result = provider(query, lookup_type=lookup_type)
        if not isinstance(result, dict):
            result = {"ok": False, "status": "invalid_result"}
        self._cache[key] = dict(result)
        return {**result, "cached": False}

    def resolve_many(
        self,
        requests: Iterable[dict[str, Any]],
        *,
        provider: Callable[..., dict[str, Any]],
        context_key: str = "",
    ) -> list[dict[str, Any]]:
        return [
            self.resolve(
                str(item.get("query") or ""),
                lookup_type=str(item.get("lookup_type") or "job"),
                provider=provider,
                remote=bool(item.get("remote")),
                context_key=context_key,
            )
            for item in requests
        ]

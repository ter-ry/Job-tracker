# Provider runtime integration notes

This branch keeps `fetch_jobspy_jobs(...)` backward-compatible. Real JobSpy
calls use `execution_mode="process"` by default. Injected test doubles use the
existing soft-timeout thread path; callers that explicitly need compatibility
can pass `execution_mode="thread"`. The process path uses a bounded maximum of
two provider workers, terminates and joins a timed-out child, closes its queue,
and exposes `execution_mode`, `process_pid`, and `child_terminated` in provider
diagnostics. A process timeout is hard-bounded; a thread-mode timeout is not.

Callers that perform continuation searches may pass one caller-owned
`ProviderCircuitBreaker` instance. Repeated blocked, unavailable, unsupported,
or timed-out provider states open that source temporarily; a later call after
the cooldown can retry it. A successful or genuine no-results response resets
that source's failure count.

Worker 1 integration should preserve the adapter's `source_diagnostics` and
surface the provider status without treating an empty failed result as success.
For later continuation, pass the same search parameters and a fresh call; do
not claim JobSpy cursor/offset support.

`GeocodeRuntime` in `sources/provider_runtime.py` is an optional per-search
helper for app integration. It deduplicates normalized lookup queries, skips
confirmed remote jobs, and scopes cache entries by lookup type, provider, and
applicant context key. It does not replace the app's database cache or invent
coordinates. The integrator should call it after occupation/seniority screening
and retain the existing precision/confidence labels.

For Windows frozen builds, `release_packaging/windows/launcher.py` calls
`multiprocessing.freeze_support()` before starting the app. The existing
`job_tracker.spec` already bundles `sources`; if PyInstaller's static analysis
misses the worker, add `sources.jobspy_worker` and
`sources.provider_runtime` to `hiddenimports`. No dependency upgrade is
required.

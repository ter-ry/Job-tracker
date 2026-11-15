# Provider runtime performance evidence — 2026-11-15

## Process isolation

Using the pinned `python-jobspy==1.1.82` and the real adapter:

```text
software engineer / Toronto, Ontario / LinkedIn / provider_timeout_seconds=3
state=timed_out, execution_mode=process, child_terminated=True
```

The call returned within the configured bound and no provider thread was left
in the parent. The isolated child was terminated and reaped. This validates the
hard-timeout path; it does not claim that LinkedIn is unavailable in general.
The earlier six-query live provider availability observations remain recorded
in `audit/jobspy-provider-smoke-2026-11-13.md`: LinkedIn returned rows, Indeed
was proxy-blocked, ZipRecruiter was DNS-unavailable, and Glassdoor timed out.

Injected test providers intentionally use `execution_mode="thread"` because
arbitrary test callables cannot safely be transferred to a Windows spawned
child. Their timeout diagnostics remain explicitly soft and do not claim hard
cancellation.

## Offline stage benchmark

Command: `python scripts/provider_performance_benchmark.py` with synthetic
postings. Acquisition is list construction, normalization uses the real
adapter normalizer, and enrichment uses `GeocodeRuntime` with a synthetic
provider. No external service was contacted.

| postings | acquisition ms | normalization ms | geocoding/enrichment ms | total ms | unique geocode calls |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 50 | 0.001 | 52.037 | 0.129 | 52.167 | 1 |
| 200 | 0.001 | 116.492 | 0.307 | 116.800 | 1 |
| 1,000 | 0.002 | 604.864 | 1.904 | 606.770 | 1 |

The geocoding helper deduplicates repeated Toronto city-only lookups, skips
confirmed remote jobs, and scopes entries by applicant context. It does not
fabricate coordinates or replace the application database cache.

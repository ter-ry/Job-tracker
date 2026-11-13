# JobSpy provider smoke evidence — 2026-11-13

Environment: repository branch `codex/jt-jobspy-provider-stabilization`, pinned
`python-jobspy==1.1.82`, Canada, 50 km requested (adapter sends 31 miles),
168 hours, 10 requested results. Each source was called independently for
each query with a 20-second adapter timeout. Command:

```text
/tmp/job-tracker-venv/bin/python scripts/jobspy_provider_smoke.py
```

The script emits one raw-row snapshot per provider row, normalized/evidence
counters, request parameters, warnings, and errors. The table below is the
durable summary of that run; empty counts are actual observations, not claims
that a provider is healthy.

| Query | LinkedIn | Indeed | ZipRecruiter | Glassdoor |
| --- | --- | --- | --- | --- |
| Toronto junior software developer | working: 10 raw / 10 normalized / 10 returned | blocked: Indeed GraphQL proxy 403 | unavailable: ZipRecruiter DNS failure | timed_out: Glassdoor Canada DNS timeout |
| Toronto junior software engineer | working: 10 / 10 / 10 | blocked: Indeed GraphQL proxy 403 | unavailable: ZipRecruiter DNS failure | timed_out: Glassdoor Canada DNS timeout |
| Toronto Registered Early Childhood Educator | working: 10 / 10 / 9 (one outside 168h) | blocked: Indeed GraphQL proxy 403 | unavailable: ZipRecruiter DNS failure | timed_out: Glassdoor Canada DNS timeout |
| Mississauga RECE | working: 10 / 10 / 10 | blocked: Indeed GraphQL proxy 403 | unavailable: ZipRecruiter DNS failure | timed_out: Glassdoor Canada DNS timeout |
| Canada remote software developer | working: 10 / 10 / 9 (one outside 168h) | blocked: Indeed GraphQL proxy 403 | unavailable: ZipRecruiter DNS failure | timed_out: Glassdoor Canada DNS timeout |

For every LinkedIn row in this run, the original URL and description were
available (10/10 per request); no salary or street-address evidence was
returned in these result sets. A raw example was Thomson Reuters,
`Software Engineer`, Toronto, with the authentic LinkedIn URL
`https://www.linkedin.com/jobs/view/4481189188`.

## Package verification and limitations

JobSpy 1.1.82 supports `linkedin`, `indeed`, `zip_recruiter`, and `glassdoor`
site names and has a Glassdoor scraper. JobSpy’s distance input is miles, so
the adapter records and converts the application’s kilometre input. Canada is
passed through `country_indeed="Canada"`; descriptions request Markdown and
LinkedIn description retrieval. Google remains supported by the dependency
itself, but is no longer registered or invoked by this application adapter.

ZipRecruiter was not verifiable in this environment: its request failed DNS
resolution for `api.ziprecruiter.com`. Glassdoor was not verifiable: its
Canadian request reached a DNS timeout for `www.glassdoor.ca`. Indeed was
blocked by the environment’s proxy with HTTP 403 while reaching
`apis.indeed.com`. These are reported as unavailable/blocked/timed-out, not as
successful empty searches. No authentication, anti-bot bypass, or dependency
upgrade was attempted.

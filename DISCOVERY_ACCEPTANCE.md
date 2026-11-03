# Discovery acceptance record

Date: 2026-11-02 (America/New_York)

## Validated in the current branch

- Branch: `codex/discovery-reliability`
- HEAD: `fd7161320f43d2fd9c32f8b21022fc5d89e52328` (`Fix countrywide discovery and geocode validation`)
- The branch includes the countrywide discovery and geocode-validation fix. A Canada-wide input is handled as `countrywide_scope`, does not call the geocoder, and expands into bounded queries for Toronto, Montreal, Vancouver, Calgary, and Halifax.
- Cached geocodes are revalidated against the requested Canadian city/province/postal code before reuse. Mismatched coordinates are rejected.
- The test suite completed with **205 passed, 1 skipped in 419.31s (0:06:59)**.

## Browser evidence

The visible Windows browser was tested against the existing local server on `127.0.0.1:5055` using the live discovery form with:

- Canada location
- Remote preference
- LinkedIn and Indeed enabled
- SWE résumé profile selected
- Prioritized software-development keywords

That server returned no jobs and its diagnostics reported `normalized=Canada; search=Cardston County, AB; method=geocoded_city_region`. This is the stale pre-fix server, not the current branch: it demonstrates the original defect and must not be used as acceptance evidence for the fixed code.

An isolated server using the current branch and QA data was started on `127.0.0.1:5057`, but the Windows browser could not reach the restricted execution environment (`ERR_CONNECTION_REFUSED`). Production `data/` was not used for writes.

## Remaining limitations

1. A full live LinkedIn/Indeed acceptance run could not complete in this execution environment. The current-branch provider run planned the five Canadian region queries, then JobSpy failed DNS resolution for `www.linkedin.com` (`NameResolutionError`, `[Errno 11001]`) before returning jobs. The visible Windows browser and shell are on separate local-network surfaces: the browser can reach the stale 5055 server, while it cannot reach the isolated 5057 server.
2. Because live provider responses were unavailable from the current branch, real posting descriptions, top recommendations, and browser persistence actions could not be revalidated against fresh LinkedIn/Indeed data in this run. The 205-test regression suite covers provider failure handling, deduplication, résumé matching, eligibility classification, sorting, and Applied/Skipped/Saved persistence with controlled fixtures.

The application is not being declared fully ready for manual acceptance until the current branch is run where LinkedIn and Indeed DNS/network access is available and the browser can reach that same instance.

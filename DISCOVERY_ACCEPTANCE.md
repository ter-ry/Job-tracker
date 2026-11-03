# Discovery reliability acceptance report

Date: 2026-11-03 (America/New_York)
Branch: `codex/discovery-reliability`
Scope: Issue #13 on draft PR #12

## Implemented behavior

- Country-wide Canada searches are resolved before geocoding and expanded into bounded, geographically diverse provider regions. Diagnostics expose exact region queries and per-source outcomes.
- Discovery results retain distinct actionable, review-required, and excluded outcomes, with Qualification Match and Application Priority shown separately and sorted consistently.
- The discovery inbox has persistent New actionable, Review required, Excluded, Applied, and Skipped views. Applied and skipped records remain in history and are excluded from New after reloads and reruns.
- Applied actions persist the application date. Skip actions preserve the record and source URL.
- The selected candidate profile and résumé remain the evidence source throughout discovery and saved-search views.
- Cached geocodes are revalidated against the requested Canadian city, province, or postal code before reuse; mismatched coordinates are rejected.

## Browser and fixture evidence

The browser harness is `scripts/discovery_acceptance_browser.js`. It creates a disposable database and DOCX résumé, seeds recorded Canada results from `tests/fixtures/discovery_canada_acceptance.json`, intercepts only the provider request, and runs the application in Chromium. The successful recorded-fixture run captured:

- `01-canada-search.png`: Canada search, ranked results, profile evidence, explanations, and diagnostics.
- `02-applied-skipped.png`: Applied, Skipped, and separate shortlist history state.
- `browser-log.json`: profile, seeded IDs, category assignments, and history counts.

The QA database and résumé were disposable and did not use production data.

The visible Windows browser was also exercised against the existing local server on `127.0.0.1:5055` with Canada, Remote, LinkedIn and Indeed, the SWE résumé, and prioritized software-development keywords. That server returned no jobs and reported `normalized=Canada; search=Cardston County, AB; method=geocoded_city_region`. It is a stale pre-fix server and is not acceptance evidence for the current branch; it reproduces the original defect.

## Validation

- Current full Python regression suite: **205 passed, 1 skipped in 419.31s (0:06:59)** before integrating the remote completion commit.
- The remote completion commit adds the recorded browser harness and additional discovery coverage; it still needs a fresh post-merge full-suite run before the branch can be called fully accepted.
- `git diff --check` passed for the documentation change before merge.

## Live acceptance limitation

**LIVE ACCEPTANCE BLOCKED.** The current-branch provider run planned the five Canadian region queries, then JobSpy failed DNS resolution for `www.linkedin.com` (`NameResolutionError`, `[Errno 11001]`) before returning jobs. The visible Windows browser and restricted execution environment are on separate local-network surfaces: the browser can reach the stale 5055 server, while it cannot reach an isolated current-branch server on 5057 (`ERR_CONNECTION_REFUSED`).

Because live provider responses were unavailable from the current branch, fresh LinkedIn/Indeed descriptions, top recommendations, and browser persistence actions could not be revalidated against live data in this run. Recorded fixtures cover the browser workflow, résumé matching, eligibility classification, sorting, and Applied/Skipped/Saved persistence. No applications were submitted, no paid APIs were used, production data was not modified, and PR #11, cover-letter generation, and résumé tailoring were not changed.

The application is not being declared fully ready for manual acceptance until the current branch is run where LinkedIn and Indeed DNS/network access is available and the browser can reach that same instance.

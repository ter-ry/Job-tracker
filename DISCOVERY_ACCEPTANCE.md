# Discovery reliability acceptance report

Date: 2026-11-03
Branch: `codex/discovery-reliability`
Scope: Issue #13 on draft PR #12

## Implemented behavior

- Country-wide Canada searches are resolved before geocoding and are expanded into bounded, geographically diverse provider regions. Diagnostics expose the exact region queries and per-source outcomes.
- Discovery results retain distinct actionable, review-required, and excluded outcomes, with qualification match and application priority shown separately and sorted consistently.
- The discovery inbox now has persistent New actionable, Review required, Excluded, Applied, and Skipped views. Applied and skipped records remain in history and are excluded from New after reloads and reruns.
- Applied actions persist the application date and discovery state. Skip actions preserve the record and source URL.
- The selected candidate profile and résumé remain the evidence source throughout discovery and saved-search views.

## Reproduction and evidence

The browser harness is `scripts/discovery_acceptance_browser.js`. It creates a disposable database and DOCX résumé, seeds recorded Canada results from `tests/fixtures/discovery_canada_acceptance.json`, intercepts only the provider request, and runs the application in Chromium. The successful run captured:

- `01-canada-search.png`: Canada search, ranked results, profile evidence, explanations, and diagnostics.
- `02-applied-skipped.png`: Applied, Skipped, and separate shortlist history state.
- `browser-log.json`: profile, seeded IDs, category assignments, and history counts.

The last successful artifacts were written under `/tmp/job-tracker-discovery-qa.SOaAra/artifacts`. The QA database and résumé were disposable and did not use production data.

## Validation

- Python test suite: `Ran 207 tests in 38.056s; OK (skipped=1)`.
- Browser acceptance: passed with the recorded fixture, including reload and default inbox assertions.
- JavaScript syntax: `node --check static/app.js` and `node --check scripts/discovery_acceptance_browser.js`.
- Diff hygiene: `git diff --check`.

## Live acceptance limitation

**LIVE ACCEPTANCE BLOCKED.** The public-source smoke check attempted LinkedIn, Indeed, Google Jobs, and ZipRecruiter. The managed network returned proxy or DNS failures (`403 Forbidden` tunnel failures for LinkedIn, Indeed, and Google; DNS failure for ZipRecruiter). Recorded fixtures provide evidence for the browser workflow, but live acceptance cannot be claimed until those sources are reachable.

No paid AI API, production user data, application submission, résumé rewrite, cover-letter generation, or new user-facing document rendering was used.

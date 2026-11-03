# Discovery acceptance report

Date: 2026-11-03 (America/New_York)
PR: https://github.com/ter-ry/Job-tracker/pull/12 (draft, unmerged)
Branch: `codex/discovery-reliability`
Implementation commit: `0f8482d4de1b224a3035073f5a9a01b61cd83d1d`
Report commit: `2276cf7`
Issue: https://github.com/ter-ry/Job-tracker/issues/13

## Status

Implementation complete for locally verifiable discovery and application-history behavior. Recorded-fixture browser acceptance and regression tests pass. **Live provider acceptance remains blocked** by proxy/DNS restrictions and is not claimed as passed.

## Root causes and fixes

- Canada-wide searches are resolved before geocoding and use bounded Toronto, Montreal, Vancouver, Calgary, and Halifax provider regions. Diagnostics retain source and region outcomes; cached coordinates are checked against the requested Canadian geography.
- Live search results now receive durable database IDs before rendering. Save for later, Mark Applied, and Skip use exact discovery IDs and preserve source/application URLs. Applied dates and history categories persist across reloads and repeated searches.
- Repeated searches omit durable Saved, Applied, Skipped, and legacy shortlisted records from New while retaining them in history. Canonical URLs and normalized company/title/location keys handle cross-provider and cross-region duplicates.
- Simple Save for later does not trigger résumé or cover-letter generation. The existing generation tools remain separate.
- Qualification Match and Application Priority remain separate. Required/preferred experience, candidate years when explicitly evidenced, experience fit, seniority, and source evidence are exposed in result data and directly on result rows/cards.
- The selected candidate résumé remains the evidence source through live discovery, saved searches, inbox hydration, and scoring.

## Verification

- Full Python suite after the merged PR work: `Ran 209 tests in 37.275s; OK (skipped=1)`.
- Coverage includes Canada scope, invalid geocoding, rate limits, selected-profile isolation, seniority false positives and ranking, cross-provider/cross-region deduplication, durable three-outcome actions, repeated searches, application dates/links, and no document generation from Save.
- JavaScript syntax: `node --check static/app.js` and `node --check scripts/discovery_acceptance_browser.js`.
- Diff hygiene: `git diff --check`.

## Browser evidence

`scripts/discovery_acceptance_browser.js` uses a disposable SQLite database, a temporary DOCX résumé named `SWE résumé`, and three recorded Canada results. It exercises Canada/Remote search, profile selection, ranked explanations, required/preferred experience display, original and employer links, Save for later, Mark Applied, Skip, history counters, reload, and New-inbox exclusion.

Latest successful artifacts:

- `/tmp/job-tracker-discovery-qa.lCrs9D/artifacts/01-canada-search.png`
- `/tmp/job-tracker-discovery-qa.lCrs9D/artifacts/02-applied-skipped.png`
- `/tmp/job-tracker-discovery-qa.lCrs9D/artifacts/browser-log.json`

No production database, user document, application submission, or paid API was used. PR #11 was not modified.

## Acceptance matrix

| Area | Result | Evidence |
|---|---|---|
| Canada scope, regional queries, geocoding safeguards | Pass locally | Unit coverage, diagnostics, recorded fixture |
| Qualification Match and Application Priority | Pass locally | Ranking and score explanation tests/browser evidence |
| Required/preferred years and source evidence | Pass locally | `seniority.py` tests and visible result summary |
| SWE résumé evidence isolation | Pass locally | Profile-scoped browser fixture and API calls |
| Cross-provider/cross-region deduplication | Pass locally | Canonical identity tests and repeated-search test |
| Save for later without generation | Pass locally | Durable action API test and browser workflow |
| Applied/Skip persistence and reload | Pass locally | Three-outcome integration test and browser workflow |
| Corrective workflow | Pass locally | Explicit inbox state endpoints and history access |
| Live provider search and top-ten audit | Blocked | Provider proxy/DNS failures |

## Live limitation and wake-up step

**LIVE ACCEPTANCE BLOCKED.** The bounded provider check attempted LinkedIn, Indeed, Google Jobs, and ZipRecruiter. LinkedIn, Indeed, and Google returned proxy tunnel `403 Forbidden`; ZipRecruiter returned DNS failure. The earlier Windows-visible server was stale pre-fix code, so it is not current-branch evidence.

When provider access is available on Windows, run one isolated Canada remote SWE search against the current branch, inspect the first ten results for source/application links, experience evidence, eligibility, and the SWE profile name, then mark one Saved, one Applied, and one Skipped and repeat the search after reload. This is the only remaining live check; no database repair or manual code change should be needed.

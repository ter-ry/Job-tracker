# Discovery acceptance report

Date: 2026-11-03
PR: https://github.com/ter-ry/Job-tracker/pull/12 (draft, unmerged)
Branch: `codex/discovery-reliability`
Issue: https://github.com/ter-ry/Job-tracker/issues/13

## Status

Implementation complete for the locally verifiable workflow. Regression tests and recorded-fixture browser acceptance pass. **Live provider acceptance remains blocked** by the managed network and is not claimed as passed.

## Defects and fixes

- Canada-wide searches now resolve country scope before geocoding and use bounded Toronto, Montreal, Vancouver, Calgary, and Halifax provider queries. Diagnostics retain region and provider outcomes.
- Search results now persist discovery identity when the user chooses Save for later, and the discovery Save action does not generate résumé or cover-letter documents.
- Applied and Skipped records are excluded from repeated manual and saved-search results while remaining in history. Cross-provider and cross-region identity matching uses canonical URLs plus normalized company/title/location keys.
- Live result Skip now writes an authoritative SQLite history record. Applied and Skipped records have a Reopen action that explicitly returns them to New.
- Required and preferred professional experience, candidate years when explicitly evidenced, experience fit, seniority, and source evidence are exposed in the result payload and directly on result rows/cards.
- The selected résumé profile remains the evidence source through discovery scoring and saved discovery views.

## Automated verification

- Full Python suite: `Ran 209 tests in 37.275s; OK (skipped=1)`.
- Targeted regressions: repeated Applied/Skipped searches, experience extraction/display data, inbox history persistence, duplicate handling, and existing seniority false-positive cases all pass.
- JavaScript syntax: `node --check static/app.js` and `node --check scripts/discovery_acceptance_browser.js`.
- Diff hygiene: `git diff --check`.

## Browser evidence

`scripts/discovery_acceptance_browser.js` creates a disposable SQLite database, a temporary DOCX résumé for the `SWE résumé` profile, and two recorded Canada results. It exercises Canada search entry, résumé selection, ranked results, score explanations, required/preferred experience display, application links, Save for later, Mark Applied, Skip, history counts, reload, and default-inbox exclusion.

Latest successful artifacts:

- `/tmp/job-tracker-discovery-qa.JSYL4N/artifacts/01-canada-search.png`
- `/tmp/job-tracker-discovery-qa.JSYL4N/artifacts/02-applied-skipped.png`
- `/tmp/job-tracker-discovery-qa.JSYL4N/artifacts/browser-log.json`

The QA database and résumé were disposable. No production records or personal documents were used.

## Acceptance matrix

| Area | Result | Evidence |
|---|---|---|
| Canada scope and geocoding safeguards | Pass locally | Existing unit coverage plus regional diagnostics and Canada fixture |
| Qualification Match and Application Priority | Pass locally | Existing scoring tests and browser explanations |
| Required/preferred years extraction | Pass locally | Seniority tests and new response/UI regression |
| SWE résumé evidence isolation | Pass locally | Candidate-profile browser fixture and profile-scoped API calls |
| Provider/cross-region deduplication | Pass locally | Canonical URL and company/title/location tests |
| Save for later | Pass locally | Discovery action persists identity without document generation |
| Applied and Skip persistence | Pass locally | Repeated-search regression and browser reload evidence |
| Accidental decision correction | Pass locally | Reopen endpoint and history action |
| Live provider search | Blocked | Network proxy/DNS failures |

## Live limitation

**LIVE ACCEPTANCE BLOCKED.** The bounded public-source check attempted LinkedIn, Indeed, Google Jobs, and ZipRecruiter. LinkedIn, Indeed, and Google returned proxy tunnel `403 Forbidden`; ZipRecruiter returned DNS failure. Do not treat recorded fixtures as live acceptance.

## Windows follow-up

After network access is available on the host, run the browser harness against an isolated data directory and perform one Canada remote SWE search. Confirm the first ten provider results include source URLs, required-years evidence, and the selected résumé name; mark one Applied, one Skip, and one Save for later; reload and repeat the search. The code and report already preserve the required local evidence, so this is the remaining live check rather than a database repair.

No paid AI API, application submission, automatic Applied action against production data, résumé rewrite, cover-letter generation, or PR merge was performed. PR #11 was not modified.

# PR #17 focused factual acceptance — 2026-11-09

## Decision

**INCONCLUSIVE.** The factual parser sample passes its measurable thresholds after two confirmed salary fixes and one experience-context fix, but the requested live ECE workflow could not obtain records in this restricted environment. No ranking, direct-match, pay-retention, or original-link conclusion is claimed for that live run.

## Sample and evidence

- 20 unique explicit-pay postings: 10 ECE and 10 software. Evidence came from employer PDFs, employer ATS pages, and Government of Canada Job Bank posting snapshots. The checked records include hourly ECE pay and annual software pay.
- 10 unique authoritative ATS/employer snapshots with no compensation statement in the checked content. This means “not specified in the checked posting,” not “the employer never pays.” One duplicate explicit-pay record was excluded from this denominator.
- The same 20 explicit-pay records supplied ECE-inclusive experience and location/arrangement labels. Numeric requirements, credential-only requirements, and unspecified years were kept distinct.
- All replayed data used a disposable SQLite database. No production database, profile, saved search, or job row was opened.

## Measured results

| Criterion | Correct | Denominator | Result | Threshold | Decision |
|---|---:|---:|---:|---:|---|
| Exact salary endpoints, cadence, currency | 20 | 20 | 100% | ≥95% | PASS |
| Authoritative no-pay cases remain unspecified | 10 | 10 | 100% | 10 cases | PASS |
| Required-experience extraction, ECE-inclusive | 20 | 20 | 100% | ≥90% | PASS |
| Location and work arrangement normalization | 20 | 20 | 100% | 20 cases | PASS |
| Professional-credential evidence handling | 20 | 20 | 100% | No invented credentials | PASS |

The reproducible machine-readable labels and URLs are in `audit/occupation-factual-acceptance-20261109.json`.

## Confirmed corrections

1. Salary ranges such as `$18.00-$21.00`, `$24.47-$28.36`, and `CA$90,000–CA$130,000` now preserve both endpoints, including decimals and a currency prefix only on the first endpoint.
2. Legitimate high annual ranges such as `CA$157K-$367K` are no longer rejected by the plausibility ceiling.
3. Experience phrases such as `3+ years building and shipping production software` are recognized in the evidence parser.

## Live ECE workflow

The requested isolated replay was executed with Job Title Search, related-title matching, `Registered Early Childhood Educator`, Toronto, 50 km, LinkedIn and Indeed, no selected résumé, and aggregate cap 40. It returned zero records because the restricted environment could not resolve `www.linkedin.com`, `apis.indeed.com`, or Nominatim. Therefore the live ECE prioritization, irrelevant-title exclusion, advertised-pay retention, and original-link checks remain **unverified**, not failed.

The application still records `profile_independent: true` for this title search, preserves straight-line distance only, and does not fabricate road or transit ETAs.

## PR coordination

PR #16 remains a separate draft. Its branch is an ancestor of PR #17, so the Pipeline workflow is preserved. PR #17 remains cleanly integrable after PR #16 merges; no rebase or force-push was performed and no PR #16 files were modified.

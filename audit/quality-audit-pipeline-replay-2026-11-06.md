# Captured Windows pipeline replay — 2026-11-06

Status: **INCONCLUSIVE** — this is a deterministic application-pipeline replay, not independent source verification.

## Replay integrity

| Measure | Result |
|---|---:|
| Captured provider records | 25 |
| Raw canonical postings | 20 |
| Persisted unique postings | 20 |
| Raw missing descriptions | 0 |
| Persisted missing descriptions | 0 |
| Duplicate records removed | 5 |
| Actionable | 9 |
| Review required | 6 |
| Excluded | 5 |

The records were replayed through `jobspy_result_to_job_payload`, `normalize_job_payload`, geocoding/eligibility assessment, qualification extraction, SWE résumé matching, application-priority scoring, deduplication, and persistence in a temporary copy of the isolated QA database.

## Application-ranked top 20

| Rank | Company | Title | Priority | Qualification | Category | Required experience |
|---:|---|---|---:|---:|---|---|
| 1 | Proven | Junior Software Developer | 73 | 59 | actionable | — |
| 2 | PRI Engineering | Junior Software Developer | 72 | 59 | actionable | — |
| 3 | Rose Rocket | Junior Software Engineer | 69 | 59 | actionable | — |
| 4–7 | Affirm | Software Engineer I, Fullstack (Search) | 63 | 59 | actionable | — |
| 8 | Joblet-AI | Fullstack Software Engineer (Remote) | 59 | 53 | review_required | — |
| 9 | Quora | Full Stack Software Engineer, New Grad | 59 | 79 | review_required | — |
| 10 | DoorDash | Software Engineer, Entry-Level | 58 | 34 | review_required | — |
| 11–12 | Genesys | Associate Software Developer | 56 | 37 | review_required | 0 to 2 years |
| 13 | Thomson Reuters | Software Engineer | 55 | 52 | actionable | 1–3+ years |
| 14 | Didero | Forward Deployed Engineer | 50 | 33 | actionable | — |
| 15 | Super.com | Head of Security | 39 | 39 | review_required | — |
| 16–20 | AlayaCare, Capital One, Intuit, Method Integration | Mixed roles | 0 | 37–59 | excluded | Capital One: 6 years |

## Latest Windows replay correction

The final Windows artifacts contain 27 raw records, 21 unique canonical postings, 21 persisted unique jobs, and 6 duplicate records removed before persistence. The current ranking is 9 actionable, 6 review-required, and 5 excluded; no persisted description is missing. This replay exercises the real persistence, qualification, eligibility, résumé matching, and application-priority pipeline.

An independent source review matched 18 of the captured top 20 to authoritative employer/ATS or exact LinkedIn/Indeed pages; Joblet-AI and Kablamo remain unresolved. Because those checks were not recorded as the required structured annotations, `independently_verified_count` remains 0 in the JSON audit and the 40-posting acceptance sample was not met. Precision, required-years accuracy, mandatory-skill accuracy, eligibility error rate, and false-positive/negative rates remain unavailable. Final status: **INCONCLUSIVE**.

## Scenario-aware replay correction — 2026-11-07

The earlier category totals were calculated from the top 20 only. The complete persisted set is 21 rows: 9 actionable, 6 review-required, and 6 excluded, with Verismo Health outside the top 20. The replay now retains each duplicate posting's scenario-specific score and category and ranks the durable row using its best valid scenario. The corrected complete-set totals are 13 actionable, 6 review-required, and 2 excluded; Intuit's Toronto-hybrid result is now actionable at priority 55 rather than inheriting the Canada-remote exclusion.

The structured adjudication is recorded in `audit/discovery-adjudication-2026-11-07.json/.md`: 40 unique records, 20/20 top-ranked rows adjudicated, top-20 precision 12/18 (66.67%), required-experience accuracy 1/5 (20%), eligibility error rate 1/20 (5%), and mandatory-skill accuracy unavailable. Numeric quality thresholds are not stated in `DISCOVERY_ACCEPTANCE.md`, so the final gate remains **INCONCLUSIVE**.

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

No original posting was independently fetched and adjudicated. Consequently precision, experience accuracy, mandatory-skill accuracy, eligibility error rate, and false-positive/negative rates remain unavailable.

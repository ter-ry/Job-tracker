# Goal C — Discovery Integration Acceptance Matrix

This matrix is the executable evidence map for durable matching integration,
historical criteria, workplace/geographic reliability, and discovery accounting.
Owner data and live provider access are not used by these tests.

| Scenario | Executable evidence | Status |
|---|---|---|
| A. Shared ranking across persisted Inbox pages | `tests/test_goal_c_integration.py::test_ece_employment_ranking_persists_across_inbox_pages_and_reopen` | Complete |
| B. ECE employment status/evidence survives reopen | Same integration test; `discovery_employment_status` and evidence columns | Complete |
| C. Supply remains visible at the bottom of the normal ECE Inbox/Fast Apply queue and never satisfies acquisition target accounting | `test_supply_never_satisfies_ece_target_accounting`; integration pagination test | Complete |
| D. Technical adjacent occupations remain eligible | Goal B integration-path fixtures in `tests/test_goal_b_matching.py` | Complete |
| E–I. Effective criteria, reassessment safety, and historical preview | Existing `tests/test_final_acceptance_corrections.py` reassessment/criteria tests; membership `criteria_json` persists effective fields | Regression-covered; owner replay pending |
| J–K. Single-origin derivation and failed geocoding uncertainty | Existing discovery location and unresolved-origin tests | Regression-covered |
| L–N. Description workplace evidence and distance precision labels | `tests/test_workplace_enrichment.py`, `tests/test_workplace_evidence_diagnostic.py`, browser enrichment test | Regression-covered; synthetic evidence only |
| O–P. Repeated denial handling and remote enrichment avoidance | Existing workplace/provider replay tests | Regression-covered; no live provider claims |
| Q–R. Previously acquired and cross-source canonical accounting | Canonical reconciliation and discovery acceptance suites | Complete in sanitized fixtures |
| S–T. Continuation, cursors, partial provider failures | `tests/test_async_discovery_search.py` | Regression-covered |
| U. Incremental decisions and applicant isolation | discovery Inbox/Fast Apply browser tests and applicant-state suites | Regression-covered |
| V. Applicant isolation | discovery and Fast Apply browser regressions | Complete |
| W. 10,000-record performance | `tests/test_mvp_performance.py` | Complete |

The private owner cohort, live provider reliability, and independently labelled
100-posting quality evaluation remain owner-only gates. This document does not
claim those gates passed.

# Remaining Backend and Goal D Acceptance

This document records focused evidence for the final functional backend batch.
Fixtures are synthetic; no owner database, private cohort, or live provider was
used.

| Defect | Regression evidence | Implementation | Limitation |
|---|---|---|---|
| ECE queue eligibility differs from full-time acquisition targeting | `tests/test_goal_d_integration.py::test_ece_queue_keeps_supply_but_target_counts_only_full_time` exercises mocked acquisition, geographic filtering, persistence, Inbox and queue ordering | `discovery_target_eligible`, ECE pipeline target accounting, shared geographic gate | Provider quality and owner-labelled quality remain owner gates |
| Target completion does not hide pending work | `tests/test_discovery_acceptance.py::test_target_pacing_continues_until_qualifying_target`, `test_linkedin_failure_does_not_stop_later_indeed_batches` | `fetch_discovery_jobs_for_search` continuation contract | A short provider page is not proof of exhaustion |
| Acquisition accounting distinguishes new, attachments, unseen and presented rows | Goal C integration and pipeline diagnostics (`newly_acquired_count`, `new_source_attachment_count`, `previously_acquired_unseen_count`, `previously_presented_count`, `newly_presented_count`) | `persist_discovery_jobs`, `run_discovery_pipeline` | Counts are scoped to the selected execution/applicant |
| Repeated workplace denial is bounded | `tests/test_workplace_enrichment.py` blocked-source coverage plus provider cache path | `enrich_existing_workplace_locations`, `_automatically_enrich_indeed_jobs` | Only approved public Indeed URLs are retrieved; no automatic employer-site discovery is claimed |
| Stored workplace evidence is preferred | Existing workplace enrichment tests cover saved description/provider evidence before network | `_stored_workplace_alternatives` and enrichment loops | Candidate addresses remain unconfirmed until explicit owner action |
| Applicant switch invalidates stale UI state | `node --check static/app.js`, browser regressions, applicant-scoped API ownership tests | `invalidateApplicantContext`, request tokens, `validate_discovery_action_owner` | Full visual redesign is intentionally out of scope |
| Fast Apply durable queue and action ownership | Existing Fast Apply browser suite plus Goal C pagination/reopen coverage | Persistent Inbox inventory, applicant-scoped action validation | Owner live queue was not accessed |
| Unsafe reconciliation rollback is rejected atomically | `test_M_L_rollback_restores_relationship_and_decisions_without_losing_later_change` | Rollback preflight and 409 conflict response | Historical owner reconciliation remains prohibited |

Remaining owner-only gates: private owner-cohort replay, live provider
reliability, and the independently labelled 100-posting evaluation. No
applications, production mutations, ScraperAPI requests, releases, or tags are
performed by this batch.

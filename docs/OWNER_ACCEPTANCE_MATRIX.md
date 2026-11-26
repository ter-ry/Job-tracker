# Owner acceptance correction matrix

This matrix records the correction scope for the owner acceptance report. The
browser evidence uses sanitized fixtures; it does not modify or replay the
owner database.

| Defect / acceptance gate | Implementation or regression evidence | Status |
| --- | --- | --- |
| Five distinct workspaces; one global applicant selector; no redundant discovery subnav | `tests/test_owner_acceptance_ui_browser.js` verifies Discover, Job Inbox, Fast Apply, Applications and Settings navigation plus selector-driven workflow | Pass |
| Workflow-specific Discover fields and commute-origin location authority | `tests/test_owner_acceptance_ui_browser.js` switches to ECE and verifies `ece`, RECE/ECE keywords, no Search Area, and no batch workplace controls | Pass |
| Batch workplace preview / Find Workplace / Next Batch removed | `templates/index.html` contains no batch controls; individual Inbox verification and map links remain in `static/app.js` | Pass |
| Persistent Fast Apply queue is not truncated | `tests/test_fast_apply_browser.js` loads 501 records using authoritative response totals and page metadata | Pass |
| Queue applicant ownership and stale-response protection | `tests/test_fast_apply_browser.js` races applicant 2 and applicant 1 loads and verifies applicant 1 remains authoritative | Pass |
| Fast Apply missing evidence profile name | `tests/test_fast_apply_browser.js` renders a persisted fixture without `qualification_evidence_profile_name` and asserts no browser exception | Pass |
| Save / Skip synchronization and failure retention | `tests/test_fast_apply_browser.js` verifies successful Save advances and failed Skip keeps the same record visible | Pass |
| Accurate queue progress, counters, completion and restart recovery | `tests/test_fast_apply_browser.js` checks initial total, processed/remaining output, counter refresh and reload recovery | Pass |
| Inbox category model | `tests/test_owner_acceptance_ui_browser.js` verifies Ready/New/Saved/Applied/Skipped/All navigation surface | Pass |
| Canonical duplicate safety and geographic compatibility | `tests/test_canonical_reconciliation_acceptance.py`, `tests/test_final_acceptance_corrections.py` | Pass |
| SWE / ECE recall-first classification corrections | `tests/test_goal_c_integration.py`, `tests/test_goal_d_integration.py`, `tests/test_final_acceptance_corrections.py` | Pass |
| Historical reassessment preview and apply persistence | Goal C/D integration regressions cover preview-before-apply and derived-field persistence | Pass |
| Historical reassessment with unchanged category (Samsara-style) | `test_samsara_reassessment_updates_unchanged_actionable_derived_fields_and_reopens` covers preview, confirmed apply, and database reopen | Pass |
| Latest ECE acquisition accounting | `test_ece_persisted_search_accounting_distinguishes_new_represented_and_reclassified`; UI exposes canonical/source-attachment/previously-acquired/reclassified/presented counts | Fixture evidence only |
| Owner replay harness | `scripts/replay_owner_cohort.py --audit-dir <private-export-dir> --db-path <qa-db> --output <report.json>` copies the DB and emits duplicate groups, rejection reasons, occupational classifications and ranking fields | Executable; owner export required |
| Owner-cohort replay and named owner evidence exports | Repository audit exports loaded 78 records in an isolated copy; the documented 104-candidate owner export was not present | Not performed |

## Verification boundary

No production database, paid provider request, scraping run, automatic
application, merge, tag, or release was performed. The owner-reported cohort
counts and latest ECE search accounting require the owner’s database and named
exports for final replay; they must not be inferred from the sanitized browser
fixtures.

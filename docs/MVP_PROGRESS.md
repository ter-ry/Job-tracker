# Job Tracker MVP Progress

Updated during the continuing PR #43 implementation. Current branch starts at
`8d709bff1d6d0510a4547237040dc95335f49afc`; attachment directories are
user-provided and remain untracked.

| Workstream | Current state | Evidence | Next action |
|---|---|---|---|
| Fast Apply ownership/pagination/actions | Implemented and browser-verified | `tests/test_fast_apply_browser.js` passed after applicant-selection race fix | Exact-head Windows CI |
| SWE global ranking/recall | Goal B contextual relevance, broad recall, and neutral unknown-seniority ranking implemented; owner replay pending | `tests/test_goal_b_matching.py`, `test_swe_owner_search_quality.py`, full suite | Independent 100-posting labelled evaluation |
| ECE policy | Goal B title/context employment classification and permanent/temporary/supply ranking implemented; owner replay pending | `tests/test_goal_b_matching.py`, pipeline and policy fixtures | Owner replay pending |
| Single-origin workflow | Implemented for UI/config/geocoding; owner replay pending | Config, unresolved-origin, and applicant-switch browser paths | Owner replay unavailable |
| Effective criteria persistence | Partial | Membership schema and config propagation | Verify async continuation/reassessment reopen paths |
| Canonical reconciliation | Preview/apply/rollback ledger implemented; owner confirmation required | API integration fixture, idempotence/rollback test | Add larger sanitized candidate corpus |
| Workplace/geography | Existing bounded enrichment; review pending | workplace test suite | Fix retry/precision/accounting gaps |
| Applicant/frontend isolation | Fast Apply partially covered | Fast Apply browser test | Fix Inbox/workplace/search races |
| UI diagnostics | Collapsible/dismissible controls implemented | JavaScript syntax/UI checks | Browser visual interaction coverage |
| Performance/Issue #41 | 10k Inbox page benchmark implemented; quality gates pending | `test_mvp_performance.py` | Run quality evaluation with independent labels |
| Windows CI | Previous exact-head run passed before Goal B changes | PR history; new head validation required | Verify exact new head |
| Owner cohort replay | Blocked by private data/authorization | Not available | Owner-side QA only |

Goal B's detailed acceptance matrix is maintained in
[`MVP_MATCHING_ACCEPTANCE.md`](MVP_MATCHING_ACCEPTANCE.md). Its sanitized
fixtures are not a substitute for the private 100-posting labelled evaluation;
no live owner-cohort replay was performed in this environment.

Goal C's durable discovery integration matrix is maintained in
[`MVP_DISCOVERY_ACCEPTANCE.md`](MVP_DISCOVERY_ACCEPTANCE.md). Durable ECE
employment status/evidence and the shared Inbox ranking contract are now
covered by an actual multi-page database reopen test; live owner/provider gates
remain explicitly outstanding.

Canonical vacancy acceptance evidence is maintained in
[`MVP_CANONICAL_ACCEPTANCE.md`](MVP_CANONICAL_ACCEPTANCE.md). The A–Q table is
limited to sanitized database/API fixtures; the owner's 104 duplicate
candidates were not replayed.

# Job Tracker MVP Progress

Updated during the continuing PR #43 implementation. Current branch starts at
`8d709bff1d6d0510a4547237040dc95335f49afc`; attachment directories are
user-provided and remain untracked.

| Workstream | Current state | Evidence | Next action |
|---|---|---|---|
| Fast Apply ownership/pagination/actions | Implemented and browser-verified | `tests/test_fast_apply_browser.js` passed after applicant-selection race fix | Exact-head Windows CI |
| SWE global ranking/recall | Existing implementation; adversarial review pending | `test_swe_owner_search_quality.py`, full suite | Add remaining contextual fixtures |
| ECE policy | Implemented in current batch; owner replay pending | Pipeline and policy fixtures | Add deeper description/workplace examples |
| Single-origin workflow | Implemented for UI/config/geocoding; owner replay pending | Config, unresolved-origin, and applicant-switch browser paths | Owner replay unavailable |
| Effective criteria persistence | Partial | Membership schema and config propagation | Verify async continuation/reassessment reopen paths |
| Canonical reconciliation | Preview/apply/rollback ledger implemented; owner confirmation required | API integration fixture, idempotence/rollback test | Add larger sanitized candidate corpus |
| Workplace/geography | Existing bounded enrichment; review pending | workplace test suite | Fix retry/precision/accounting gaps |
| Applicant/frontend isolation | Fast Apply partially covered | Fast Apply browser test | Fix Inbox/workplace/search races |
| UI diagnostics | Collapsible/dismissible controls implemented | JavaScript syntax/UI checks | Browser visual interaction coverage |
| Performance/Issue #41 | 10k Inbox page benchmark implemented; quality gates pending | `test_mvp_performance.py` | Run quality evaluation with independent labels |
| Windows CI | Previous owner-reported run only | PR history | Verify exact new head |
| Owner cohort replay | Blocked by private data/authorization | Not available | Owner-side QA only |

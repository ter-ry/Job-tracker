# Job Tracker MVP Validation Log

## Baseline

- Repository: `ter-ry/Job-tracker`
- Branch: `codex/jt-primary-search-p0`
- PR: `#43` (draft, unmerged)
- Starting commit: `8d709bff1d6d0510a4547237040dc95335f49afc`
- Owner exports (`swe-cross-source-audit.json`, `swe-three-source-audit.json`,
  `ece-discovery-audit.json`) are not available in the workspace.

## Previously executed evidence

- Python full suite: `519 passed, 1 skipped, 2 warnings` at the prior batch.
- Fast Apply browser regression: passed against an isolated Flask process.
- JavaScript syntax and discovery UI checks: passed.
- Inbox browser click regression: passed against an isolated Flask process on
  port 5001; the earlier timeout was caused by the stale debug server process.
- Workplace enrichment browser regression: passed.
- Duplicate-resolution browser regression: passed.
- 10,000-record Inbox benchmark: passed in 0.99 seconds for a 50-row page.
- Final Python suite before the canonical reconciliation batch: `522 passed, 1 skipped,
  2 warnings`.
- Canonical reconciliation acceptance suite: `10 passed, 1 warning` in the
  final focused run.
- Final Python suite after the canonical reconciliation batch: `532 passed, 1
  skipped, 2 warnings`.
- Canonical candidate generation benchmark: 10,000 mixed records, bounded
  blocking, fewer than 1,000 pair comparisons, under 3 seconds in the
  executable regression.
- Fresh Chromium browser suite after the applicant-selection race fix:
  Inbox, Fast Apply, workplace enrichment, and duplicate-resolution scripts all
  passed. The workplace test covers a delayed profile-load scenario and a
  persisted ECE search run.
- Final JavaScript syntax/UI checks: passed.

## Current implementation evidence

- Reconciliation endpoints: `/api/discovery/reconciliation/preview`,
  `/<id>/apply`, and `/<id>/rollback`; apply requires the preview token and
  `confirm=true`, stores a backup, and is idempotent.
- Canonical rows use `jobs.canonical_job_id`; source rows remain durable and
  are excluded from active Inbox views only after explicit reconciliation.
- Commute origin no longer has a Fairview Mall fallback. Applicant profile
  origin is loaded or the field remains empty; a single origin can resolve the
  provider search location.

## Required commands for the continuing loop

```text
PYTHONPATH=/tmp/jobtracker-test-deps python -m pytest -q
node --check static/app.js
node tests/test_discovery_ui.js
JOB_TRACKER_URL=http://127.0.0.1:5000 node tests/test_fast_apply_browser.js
JOB_TRACKER_URL=http://127.0.0.1:5000 node tests/test_discovery_inbox_browser.js
```

## Reporting rules

Each new entry must identify whether it is unit, integration, browser, Windows
CI, or owner-live evidence. A green unit suite does not close a browser or
owner-cohort requirement. No production database, owner database, automatic
application, ScraperAPI spend, merge, tag or release is permitted.

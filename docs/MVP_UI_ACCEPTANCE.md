# MVP UI acceptance evidence

Goal E introduces a five-workspace desktop shell while retaining the existing
local-first application workflows. The browser evidence below is generated
from sanitized QA fixtures; it must not be replaced with screenshots of the
owner's database.

## Captured views

The integration run writes screenshots to `artifacts/ui-acceptance/` when the
browser fixture server is available:

- `discover-swe.png`
- `discover-ece.png`
- `job-inbox.png`
- `fast-apply-swe.png`
- `fast-apply-ece.png`
- `applications.png`
- `settings-profiles.png`
- `dark-mode.png` and `light-mode.png`
- `search-complete-continuation.png`
- `applicant-switch-cleared.png`
- `collapsed-workplace-preview.png`

The screenshots are evidence of rendered, interactive pages—not static design
mockups. The browser regression also verifies navigation, applicant switching,
queue pagination above 500 records, successful and failed actions, counter
synchronization, progress/completion, and refresh/restart recovery.

## Honest scope

The private 494-record owner-cohort replay, independent 100-posting recall /
precision study, safe historical reconciliation, repeated Employer Direct
coverage, and real-world workplace accuracy remain owner-only acceptance gates.
They were not run by this repository regression.

## Owner QA

1. Start the Windows launcher with the application database selected.
2. Choose an applicant from the global selector and confirm the workflow badge.
3. Run a small SWE search, switch to the Inbox, then open Fast Apply without
   starting another search.
4. Open the external posting, return to the app, and use Confirm Applied only
   after submitting externally; use Save for Later or Skip for other outcomes.
5. Switch applicants while a search or queue load is in progress and confirm
   that the previous applicant's rows and counters do not reappear.
6. Use Settings / Profiles for documents, saved origins, saved searches and
   advanced diagnostics. Do not use QA reset controls on the owner database.

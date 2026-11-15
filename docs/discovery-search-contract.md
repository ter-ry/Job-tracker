# Discovery search contract

Discovery’s default target is 50 qualifying new jobs.  It is not a raw-row
limit: duplicates, applicant-scoped processed records, excluded records, and
review-required records do not count toward the target.

Seniority and geography use three-valued evidence rather than treating missing
posting fields as failures. A clearly relevant role with no stated seniority
and no confirmed excessive experience is a **provisional match** when the
user enables provisional inclusion (the default); it is never labelled as a
verified junior role. Explicit seniority or confirmed required experience over
the selected maximum remains ineligible. Likewise, city/region evidence may
be retained as a provisional geographic match; strict-radius mode requires a
verified workplace distance. Remote Canadian-eligible jobs have no commute
distance requirement.

JobSpy has no portable cursor for every supported provider. Discovery uses a
recorded sequence of distinct occupation queries rather than repeating the
first page. Each run stores attempted and pending `{location, keywords}` query
batches. A request with `continue_search: true` uses the same search signature
and skips completed batches. An incomplete target is reported as one of
`target_reached`, `planned_queries_completed`,
`provider_blocked_or_unavailable`, or `request_budget_reached_resumable`; a
short page is never claimed to prove total provider exhaustion.

Provider calls run with a bounded two-source concurrency limit and a strict
request budget. A JobSpy timeout is reported as an uninterruptible upstream
operation that timed out locally; successful providers' rows are retained.
Continue Search has one result-area control and one POST contract. It merges
new durable records without repeating completed batches; a failed batch stays
eligible for a later retry.

Skip, save, and applied states can be scoped by `applicant_profile_id`.  The
additive `discovery_applicant_states` table keeps one applicant’s actions from
hiding a shared source vacancy from another applicant.  Calls without an
applicant retain legacy job-level history.  This does not alter schema-14
migration semantics.

The active source configuration is LinkedIn, Indeed, Glassdoor, and
ZipRecruiter.  Historical saved Google selections are ignored safely during
normalization; they are not sent to JobSpy.

## Asynchronous search API

`POST /api/discovery/searches` with an unnamed payload containing `keywords`
queues a search and returns HTTP 202 with `{ "search_id": "...", "status":
"queued" }`. Named payloads retain the saved-search CRUD behavior.

`GET /api/discovery/searches/{search_id}?after=0` returns the durable status,
progress, result jobs, `next_sequence`, `continuation_available`,
`termination_reason`, timings, and provider errors. Result records include a
monotonic `result_sequence`; clients pass the last sequence they have received
as `after` on the next poll. Status requests do not run providers.

`POST /api/discovery/searches/{search_id}/cancel` records cancellation and
preserves completed results. It does not claim to forcibly terminate an
already-running upstream scraper. `POST /api/discovery/searches/{search_id}/continue`
queues the next attempt only when the durable search has pending/retryable work.
Interrupted `running` rows are marked `paused` with
`termination_reason=application_restarted` during database initialization.

# Discovery search contract

Discovery’s default target is 50 qualifying new jobs.  It is not a raw-row
limit: duplicates, applicant-scoped processed records, excluded records, and
review-required records do not count toward the target.

JobSpy has no portable cursor for every supported provider.  Discovery uses a
recorded sequence of distinct occupation queries rather than repeating the
first page.  An incomplete target is reported as one of `target_reached`,
`verified_provider_exhausted`, `provider_blocked_or_unavailable`, or
`request_budget_reached_resumable`; it is never silently described as
exhaustion.

Skip, save, and applied states can be scoped by `applicant_profile_id`.  The
additive `discovery_applicant_states` table keeps one applicant’s actions from
hiding a shared source vacancy from another applicant.  Calls without an
applicant retain legacy job-level history.  This does not alter schema-14
migration semantics.

The active source configuration is LinkedIn, Indeed, Glassdoor, and
ZipRecruiter.  Historical saved Google selections are ignored safely during
normalization; they are not sent to JobSpy.

# Discovery search contract

Discovery search accepts `target_matches` (default `25`). It is a qualification
target, not a raw-listing limit: providers are inspected through the configured
search budget and duplicate, processed, excluded, and review-required records
are not counted as qualifying matches.

The response remains backward compatible with the `jobs` list. New consumers
should use:

- `qualifying_new_jobs`: genuinely qualifying, unprocessed opportunities (up to
  the target for display);
- `review_required_jobs`: records retained because evidence is incomplete or
  conflicting and a person must review them;
- `qualifying_new_count`, `review_required_count`, `raw_fetched_count`,
  `already_processed_count`, `previously_skipped_count`, `duplicates_count`,
  `excluded_count`;
- `search_termination_reason`: `target_reached`, `sources_exhausted`, or
  `provider_failure`;
- `continuation_available` and `source_diagnostics`.

Skip, save, and applied state may be scoped with `applicant_profile_id`. These
states are stored in an additive `discovery_applicant_states` table, so one
applicant's skip does not hide the same vacancy from another applicant. Calls
without an applicant ID retain the legacy job-level behavior. The database
schema version remains 14.

Source configuration now exposes LinkedIn, Indeed, Glassdoor, and ZipRecruiter.
The JobSpy/provider adapter is owned by Worker 2; this backend contract does
not change `sources/jobspy_source.py`. Glassdoor wiring must be coordinated
there before it is considered live.

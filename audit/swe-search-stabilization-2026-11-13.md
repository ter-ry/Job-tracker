# SWE search stabilization — 2026-11-13

This audit records the PR #18 search integration work. It does not approve a
merge, release, or processing of real applicant data.

## Mandatory coverage

- Required and preferred technologies are kept separate when headings and
  bullets collapse in extracted HTML. Requirement evidence remains tied to the
  posting text; company-stack mentions are not promoted to mandatory skills.
- Demonstrated candidate experience, explicitly missing requirements, and
  unverified requirements remain distinct. Profile-independent searches report
  candidate fit as unverified rather than inventing résumé evidence.
- A search requests a target number of new matches (default 25), while the
  provider inspection budget is separate and larger. Strong Match is never
  awarded solely because no mandatory requirements were detected.
- Clear senior/managerial SWE postings are retained in a review queue rather
  than counted toward the new-match target. Junior and early-career stretch
  roles remain eligible when the posting does not establish a hard blocker.

## Observed false-match cases addressed

- A postal-only workplace string such as `M5V 2T6` was treated as an
  out-of-area mismatch against `Toronto` without verified distance. It is now
  reviewable until location evidence is established; confirmed named-city
  mismatches remain excluded.
- The old response could conflate raw provider rows, processed rows, and the
  actionable shortlist. Responses now expose matching and review-required
  queues separately with raw/unique/processed/disqualified counts.
- The visible source list no longer presents Google Jobs; backend compatibility
  remains for legacy payloads. Glassdoor and ZipRecruiter are represented as
  provider sources without fabricating results.

## Validation and limitations

The application and foundation suite passes 301 tests with one existing skip.
JavaScript syntax and Python compilation also pass. A live bounded probe of
ZipRecruiter and Glassdoor was attempted, but this environment could not resolve
the provider hosts (DNS/TLS network errors); no live posting evidence is
claimed. Existing Windows CI evidence remains the prior private-beta artifact
recorded in `audit/final-release-acceptance-2026-11-13.md`; this change does not
modify Windows packaging or ECE extraction.

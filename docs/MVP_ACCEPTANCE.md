# Job Tracker MVP Acceptance

This checklist is the acceptance contract for PR #43. Owner counts and private
exports are evidence inputs, not fixtures: no owner database or résumé content
may be committed.

## A. Vacancy identity and history

- [ ] Cross-source identity uses provider IDs, canonical URLs, requisition IDs,
  employer aliases, and grounded description evidence; title/company alone never
  merges a vacancy.
- [ ] Negative identity cases remain separate; source URLs, provider IDs and
  applicant decisions remain preserved.
- [ ] Reconciliation has a read-only preview, evidence/confidence, explicit
  confirmation, transaction, backup, rollback and idempotence.
- [ ] Sanitized fixtures cover the documented 104 high-confidence candidates
  and negative merge cases; owner inventory is not modified.

## B. SWE matching and ranking

- [ ] Clear finance, sales, marketing, design, insurance and administrative
  occupations are excluded while plausible technical and senior IC roles remain.
- [ ] Apply Broadly remains recall-first; unknown seniority is not senior and
  no new eligibility threshold is introduced.
- [ ] Contextual title, experience, internship, age and required/preferred
  parsing is evidence-scoped and reflected in global ranking before pagination.
- [ ] Ranking tests cover ordinary developer roles, senior IC stretch roles and
  unknown seniority.

## C. ECE and single-origin search

- [ ] UI exposes Applicant, Commute From, radius, target, sources and Find Jobs
  for ECE; SWE and ECE use one origin input with no hardcoded address.
- [ ] Saved applicant origin is loaded without leaking across applicants;
  unresolved origins remain unresolved and never fall back silently.
- [ ] Full-time RECE/ECE ranks first; supply/casual remains visible at the
  bottom but cannot satisfy the full-time target; ECA-only, management,
  unrelated and regular part-time-only roles are excluded.
- [ ] Mixed RECE/ECA, misspelled supervision, generic teacher, employment
  wording and children's-age fixtures are covered through API/pipeline tests.

## D. Persistence and geography

- [ ] Manual, async, continuation, saved-search and reassessment paths persist
  applicant, workflow, policy/version, source configuration, origin evidence,
  provider location, radius and geographic mode.
- [ ] Original classification and current-policy reassessment are distinct;
  résumé evidence is applicant-scoped and historical repair is owner-confirmed.
- [ ] Workplace evidence distinguishes exact, postal, city and route precision;
  failed enrichment is cached, remote jobs are not enriched unnecessarily, and
  ScraperAPI remains disabled unless explicitly authorized.

## E. State, UI and discovery accounting

- [ ] Applicant switches clear stale results, counters, queues, searches and
  workplace previews; stale async responses and pending actions are ignored.
- [ ] Saved/skipped/applied decisions are applicant-scoped and survive restart;
  equivalent postings cannot reintroduce decisions.
- [ ] Raw, inspected, canonical, acquired, presented, duplicate and excluded
  counts are distinct; continuation and partial provider failures are truthful.
- [ ] Diagnostics and workplace previews are collapsible/dismissible; the
  workplace action is not labelled as discovery continuation.

## F. Validation gates

- [ ] Python, JavaScript and real browser integration tests pass.
- [ ] 10,000-record performance test passes with recorded timing.
- [ ] Issue #41 evaluation keeps independently labelled data and agreed gates:
  85% recall and 80% top-20 precision.
- [ ] Exact-head Windows CI passes.
- [ ] Owner live cohort acceptance is reported separately and is not claimed
  without the private exports and owner authorization.

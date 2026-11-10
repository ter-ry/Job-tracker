# Flexible occupation search acceptance report

Date: 2026-11-09 (America/New_York)
Branch: `codex/flexible-occupation-search`
Input: `.tmpqa/postmerge-live-windows-20261109.json`

## Scope

The fresh Windows capture contains 26 unique provider records across Canada-remote and Toronto-hybrid scenarios. The records were replayed through an isolated SQLite database using the current normalization, salary, qualification, eligibility, and scoring functions. The production database was not opened or modified.

The replay produced 26 normalized records from 26 inputs, 16 records with explicit compensation recognized by the parser, 10 records with no recognized compensation, and 0 estimated salaries. Missing compensation remains `Unspecified`; the application no longer invents a market range.

The new search contract is occupation-independent:

- `Job Title Search` is the default and records exact, related, or uncertain advertised-title matches. Body text cannot promote an unrelated advertised title to an exact match.
- `Explore Opportunities` retains adjacent role families for manual review and does not apply the software-target global score cap.
- Salary evidence retains source, confidence, original evidence text, cadence, currency, and ambiguity. Hourly values are annualized only as an optional comparison using the configured 40-hour/52-week convention; the original interval remains primary.
- Location distance is explicitly straight-line/approximate. Road, driving, and transit estimates are not fabricated; they are reported unavailable until a routing provider is configured.

## Acceptance matrix

| Criterion | Measured result | Denominator | Status | Evidence / limitation |
|---|---:|---:|---|---|
| Fresh records replayed through persistence/extraction/scoring | 26/26 normalized | 26 | PASS locally | Isolated SQLite replay of the Windows JSON |
| Estimated salary displayed as advertised compensation | 0 estimates created; missing remains missing | 26 | PASS locally | Regression test for missing salary and parser tests |
| Independent authoritative salary accuracy | 0 independently adjudicated records in this environment | 20 required | INCONCLUSIVE | Windows capture contains provider descriptions/URLs, not independent employer labels; no percentage is claimed |
| Experience extraction accuracy | Not independently recalculated from authoritative labels | 20 required | INCONCLUSIVE | Existing frozen acceptance target remains 90%; replay data is not treated as ground truth |
| Mandatory-skill extraction accuracy | Not independently recalculated from authoritative labels | 20 required | INCONCLUSIVE | Required versus preferred labels need authoritative adjudication |
| Location/remote/eligibility accuracy | Not independently adjudicated in this pass | 20 required | INCONCLUSIVE | Provider records are suitable for replay, not independent ground truth |
| Recommendation precision/false-positive rate | Not claimed | Independent labeled sample required | INCONCLUSIVE | No new ranking audit was substituted for the requested post-merge replay |
| Retrieval recall/search completeness | Not measurable from discovered records alone | Independent missed-opportunity holdout required | INCONCLUSIVE | Retrieval recall and recommendation recall remain separate |
| Duplicate handling | 26 input records remained 26 replay inputs; application dedupe code exercised by existing regression suite | 26 | PASS locally | Existing canonical/source identity tests plus replay |

## Remaining monitoring limitations

The live capture is valuable operational evidence, but it is not an independent authoritative adjudication set. In particular, salary, mandatory skills, freshness/activity, and search completeness should be monitored against at least 20 employer-authoritative postings for each release-quality evaluation. The next Windows-side check should collect only the missing authoritative labels and URLs, then replay those labels without tuning the implementation against them.

No production data, user profile, stored job, application record, or unrelated local change was modified.

## Focused occupation-search correction — 2026-11-09

The correction pass preserves PR #16's Pipeline workflow and keeps the legacy software role-family constant for legacy/non-title records. New Title Search records carry the requested occupation, title-match type, and a profile-independent flag.

Actual behavior now is:

- `ECE` and `RECE` recognize `Registered Early Childhood Educator`, `RECE`, `ECE`, and valid educator equivalents. Strict mode accepts only exact occupation titles; related titles such as `Early Childhood Teacher` are reviewable in related mode.
- `Civil Engineer`, `Real Estate Developer`, `ECE Sales Representative`, `Early Childhood Assistant`, `Childcare Manager`, and `Elementary School Teacher` do not become exact matches.
- Exact ECE title matches can be actionable even though their legacy role family is `other`, provided location, arrangement/eligibility, posting activity, and seniority checks do not block them.
- Title Search does not load the active résumé when no candidate profile is explicitly selected. Qualification is labeled optional and does not determine occupational relevance. Explore mode retains adjacent roles such as strategy/analyst opportunities for review.

Focused regression coverage: **6/6 tests passed** for ECE/RECE, unrelated software titles, exact ECE actionability, profile-independent qualification, and Explore behavior.

## Targeted factual-field evaluation status

The repository evidence does not contain 20 independently adjudicated employer postings with explicit compensation plus 10 independent no-salary labels. The fresh Windows capture has 16 records whose provider descriptions contain parseable compensation and 10 with no parsed compensation, but those are not independent authoritative labels and are not counted toward accuracy. Therefore salary exact accuracy is **0/0, INCONCLUSIVE**, not a fabricated percentage.

The prior authoritative experience subset remains **6/6 = 100%** for comparable required-year/range examples, but it does not satisfy the requested 20-posting ECE-inclusive denominator; the new 20-example metric is **0/20, INCONCLUSIVE** pending labels. A field-by-field location extraction comparison is likewise not present in the authoritative artifacts, so location accuracy is **0/0, INCONCLUSIVE**. Existing 20-posting independent role/location evidence remains useful for recommendation diagnostics but is not silently reused as salary or parser ground truth.

## Commute limitation and future routing design

The application continues to show approximate straight-line distance only. Road and transit ETA fields remain unavailable unless a real routing provider supplies them. A minimal future integration would use an opt-in provider such as OSRM (public/demo usage subject to its policy) or a paid provider such as Google Routes/Mapbox, with the cost and quota shown before activation. It should send only coarse geocodes or a user-approved origin, cache routes by rounded origin/destination/mode/provider/version, retain precision/confidence, honor provider rate limits, and never store a raw home address in route requests or generated reports. No paid routing dependency was added in this correction.

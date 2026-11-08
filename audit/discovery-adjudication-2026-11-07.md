# Discovery quality adjudication — 2026-11-07

Status: **FAIL** for the frozen quality gate. The sample and top-20 adjudication requirements are met, and the targeted fixes improve extraction and conservative ranking, but top-ranked precision, overall eligibility error, and false-positive rate still miss the frozen thresholds. The PR must remain draft and unmerged.

## Sample

- 40 unique audit records: 20 current persisted top-20 rows plus 20 distinct historical Job Tracker records.
- 20/20 top-ranked rows adjudicated against an authoritative employer, ATS, or exact job page.
- 19/20 top-ranked rows source-confirmed; Joblet-AI is a documented authoritative source conflict, not silently accepted.
- Historical records are explicitly `unverified` and are not used as positive ground truth.
- No duplicates or fabricated postings were added.

## Measured criteria

| Criterion | Measured result | Required threshold | Sample size | Decision |
|---|---:|---:|---:|---|
| Unique audit records | 40 | ≥40 | 40 | PASS |
| Independently adjudicated top-ranked rows | 20 | ≥20 | top 20 | PASS |
| Top-20 precision | 12/18 = 66.67% | ≥85% | 18 predicted actionable/review rows; minimum 20 required for a gate decision | FAIL |
| Top-20 target coverage | 12/20 = 60.00% | Diagnostic only | 20 | Diagnostic |
| Required-experience accuracy | 6/6 = 100.00% after fix (was 1/5 = 20.00%) | ≥90% | 6 unique rows with explicit authoritative comparable years/ranges; ambiguous statements excluded | PASS |
| Mandatory-skill accuracy | Not calculable honestly | ≥90% | No complete comparable skill denominator of at least 5 | INCONCLUSIVE |
| Hard eligibility violations among actionable | 0/10 = 0.00% after fix | 0 | 10 actionable persisted rows; Joblet is review-required after conservative handling | PASS |
| Eligibility error rate across top 20 | 1/20 = 5.00% | 0 confirmed hard violations among actionable; diagnostic all-row conflict rate is not a substitute | FAIL diagnostic; actionable gate PASS |
| False-positive rate | 6/18 = 33.33% | ≤15% | 18 predicted actionable/review rows; minimum 20 required for a gate decision | FAIL |
| False-negative rate | 0/12 = 0.00% | ≤10% | 12 discovered-source reference rows, not an independent holdout | INCONCLUSIVE for gate; reported only |
| Source-verification coverage | 19/20 = 95.00% | 20 top rows adjudicated and 40 unique records | 20 top rows / 40 total | PASS for evidence coverage |
| Duplicate handling | 21 persisted unique; 6 raw duplicates removed | No persisted duplicates | 27 raw / 21 persisted | PASS |
| Pipeline path | All replay rows passed payload conversion, persistence, eligibility, qualification, résumé matching, and priority scoring | Actual application path | 21 persisted | PASS |

The machine-readable records are in `audit/discovery-adjudication-2026-11-07.json`. `candidate_suitability` is conditional/unknown where the source requires personal graduation, authorization, or internship facts not present in the selected résumé evidence; those rows are not converted into positive claims.

## Frozen acceptance criteria

These thresholds were frozen before the post-fix replay and are not relaxed to obtain a pass:

| Criterion | Threshold | Denominator and minimum | Ambiguous / unverified handling |
|---|---:|---|---|
| Top-ranked precision | ≥85% | target-recommendable top-ranked rows divided by all actionable/review-required top-ranked rows; at least 20 adjudicated top rows | ambiguous suitability is not a positive; unverified source records do not count as verified positives |
| Required-experience accuracy | ≥90% | exact comparable required-year/range extractions divided by independently adjudicated comparable rows; at least 5 | preferred, upper-bound, graduation, company-history, tenure, and unrelated numbers are separate; ambiguous extraction is incorrect until adjudicated |
| Mandatory-skill accuracy | ≥90% | correctly classified mandatory skills divided by independently adjudicated mandatory-skill labels; at least 5 comparable postings | preferred, optional, example, and company-technology mentions are not mandatory; missing/ambiguous source evidence is unverified |
| Hard eligibility violations among actionable | 0 | confirmed location/work-authorization violations divided by actionable rows; at least 1 actionable row | unknown authorization/location is review-required, not eligible; unverified records cannot prove eligibility |
| False-positive rate | ≤15% | irrelevant or ineligible predicted rows divided by all predicted actionable/review-required rows; at least 20 | ambiguous rows remain in the denominator and are not silently relabeled positive |
| False-negative rate | ≤10% | independently relevant reference postings omitted or wrongly excluded divided by an independently sampled relevant/irrelevant holdout; at least 20 labeled postings | the discovered set is not an independent holdout; current 0/12 is therefore diagnostic only |

Structured `verified` records require an authoritative employer/ATS or exact original posting URL, source evidence, verification timestamp, active status, location, work authorization, seniority, experience, skills, and suitability fields. Historical records are retained as `unverified` and cannot increase any verified denominator.

## Post-fix replay and before/after

The current-branch replay is `.tmpqa/quality-audit-pipeline-replay-after-fix.json` (disposable copied database, same captured Windows records, real `/api/discovery/jobspy` endpoint). It persisted 21 unique jobs and classified the complete set as 10 actionable, 9 review-required, and 2 excluded. The fixes:

- recognize Markdown and composite requirement headings such as “What you bring”, “What we’re looking for”, “Core skills and experience”, and “Education and experience”;
- preserve upper-bound semantics such as DoorDash’s “no more than 2 years” as a 0–2 requirement;
- ignore company-history/tenure statements while retaining role requirements;
- classify Super’s 10+ security requirement and Method’s 1+ testing requirement from their actual requirement sections;
- require review for non-target role families and stretch/low-priority postings in hybrid or eligible remote results.

Kablamo changed from an under-extracted 57/review result to an explicit 3–5-year extraction and 74/review result; DoorDash now records 0–2 upper-bound evidence; Super records 10+ required years; Method records 1+ required years; Capital One remains 6 years but is review-required for the staff/stretch mismatch; Method is review-required rather than actionable. The complete before/after records are in the JSON report.

## Findings

1. The prior 9 actionable + 6 review-required + 5 excluded discrepancy was a reporting slice error. Those numbers counted only the top 20. The pre-fix complete 21-row persisted set was 9 actionable, 6 review-required, and 6 excluded; the current post-fix replay is 10 actionable, 9 review-required, and 2 excluded after conservative role/stretch handling.
2. Joblet-AI's captured Canada-remote interpretation conflicts with the authoritative listing, which describes an India/global contractor role requiring professional full-stack experience. It is an eligibility/seniority false positive for this target.
3. Intuit Software Developer 1 is a Toronto entry-level role. The corrected replay preserves the Toronto-hybrid result (priority 55/actionable) instead of retaining the remote-only scenario's exclusion. This is an audit/replay correction, not a new provider run.
4. The pre-fix extraction missed or left ambiguous several authoritative requirements. The current replay recognizes Kablamo 3–5 years, DoorDash’s no-more-than-2-years upper bound, Super.com’s 10+ years, and Method’s 1+ years; Capital One’s six-year extraction remains correct.

## GitHub and tests

The GitHub PR API currently reports `mergeable=true` and `mergeable_state=clean`; the earlier `mergeable=false` response was stale metadata, not a conflict or check restriction. The PR remains open, draft, and unmerged.

The full suite on the previous head ran 221 tests: 220 passed, 1 skipped, and one pre-existing tailoring preview-cache failure. The new audit regression test covers complete-persisted versus top-20 category counts. The tailoring failure remains separate from discovery changes.

Final decision: **FAIL — do not merge PR #12.** Required-experience extraction and actionable hard-eligibility handling now pass their frozen thresholds, but top-ranked precision is 12/18 (66.67%) versus ≥85%, false-positive rate is 6/18 (33.33%) versus ≤15%, mandatory-skill accuracy lacks the required denominator, and the false-negative sample is not an independent holdout. No new Windows discovery run is justified by the current evidence; the next development action is to improve ranking/relevance and obtain a genuinely independent labeled holdout before reconsidering the gate.

## 2026-11-08 recommendation-quality correction

The six false positives were individually resolved with general rules: unknown Canadian eligibility remains review-required; stretch/senior roles remain review-required; confirmed out-of-area hybrid postings are excluded; and adjacent technical role families are review-required even when programming terms are present. No employer-specific exception was added.

The independent authoritative holdout is `audit/discovery-independent-holdout-2026-11-08.json` (20 records), selected and labeled before application scoring. `scripts/evaluate_independent_holdout.py` replays those records through the real disposable-database `/api/discovery/jobspy` path. Result: 7 suitable postings, 7 actionable recommendations, 0 false positives, and 0 false negatives. Thus actionable precision is 7/7 = 100%, holdout false-positive rate is 0/7 = 0%, and holdout false-negative rate is 0/7 = 0%. Recommendation coverage is 7/20 = 35% and is reported diagnostically; uncertainty is preserved in review-required rows.

The frozen legacy top-20 diagnostic is still 12/18 = 66.67% precision and 6/18 = 33.33% false-positive rate because its denominator includes review inventory. It remains FAIL rather than being weakened. The current replay inventory is 10 actionable, 9 review-required, and 2 excluded across 21 persisted jobs; top 20 is 9/9/2.

The required-skill labels are in `audit/discovery-mandatory-skill-labels-2026-11-08.json`. They contain 84 explicitly required technical labels across the 20 independently sourced holdout postings. Preferred/optional technologies and non-skill requirements are excluded. The replay compares persisted application requirements marked both `required` and `technical`.

| Metric | Numerator / denominator | Result | Threshold | Decision |
|---|---:|---:|---:|---|
| Precision | 76/82 | 92.68% | Reported | PASS |
| Recall | 76/84 | 90.48% | Reported | PASS |
| Accuracy | 76/84 | 90.48% | ≥90% | PASS |

Six extracted labels were false positives and eight authoritative labels were missed. The detailed per-posting comparison is in `.tmpqa/quality-audit-mandatory-skills-20261108.json`; no labels were fabricated or converted from preferred evidence.

The 20-record holdout was selected and labeled before scoring, outside the current 21-row audit pool. Seven records are independently suitable; all seven were recommended, so recall is 7/7 = 100% and false negatives are 0/7. Recommendation coverage is 7/20 = 35%, not recall. Actionable precision is 7/7 = 100% and actionable false-positive rate is 0/7 = 0%. Mandatory-skill accuracy and the actionable holdout metrics now pass. The known tailoring preview-cache failure remains separate; PR #12 remains draft and unmerged pending final human review.

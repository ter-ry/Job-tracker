# Discovery quality adjudication — 2026-11-07

Status: **INCONCLUSIVE**. The sample and top-20 adjudication requirements are met, but the acceptance document does not define numeric pass thresholds for the quality metrics, and the measured experience/eligibility errors are not a defensible merge pass.

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
| Top-20 precision | 12/18 = 66.67% | Not numerically specified in `DISCOVERY_ACCEPTANCE.md` | 18 predicted actionable/review rows | INCONCLUSIVE |
| Top-20 target coverage | 12/20 = 60.00% | Not numerically specified | 20 | INCONCLUSIVE |
| Required-experience accuracy | 1/5 = 20.00% | Not numerically specified | 5 rows with explicit comparable years | INCONCLUSIVE; defect evidence |
| Mandatory-skill accuracy | Not calculable honestly | Not numerically specified | No complete comparable skill denominator | INCONCLUSIVE |
| Eligibility error rate | 1/20 = 5.00% | Not numerically specified | 20 | INCONCLUSIVE; Joblet-AI conflict |
| False-positive rate | 6/18 = 33.33% | Not numerically specified | 18 predicted actionable/review rows | INCONCLUSIVE |
| False-negative rate | 0/12 = 0.00% | Not numerically specified | 12 source-recommendable rows | INCONCLUSIVE |
| Source-verification coverage | 19/20 = 95.00% | ≥20 adjudicated; source confirmation is not itself the threshold | 20 | PASS for evidence coverage |
| Duplicate handling | 21 persisted unique; 6 raw duplicates removed | No persisted duplicates | 27 raw / 21 persisted | PASS |
| Pipeline path | All replay rows passed payload conversion, persistence, eligibility, qualification, résumé matching, and priority scoring | Actual application path | 21 persisted | PASS |

The machine-readable records are in `audit/discovery-adjudication-2026-11-07.json`. `candidate_suitability` is conditional/unknown where the source requires personal graduation, authorization, or internship facts not present in the selected résumé evidence; those rows are not converted into positive claims.

## Findings

1. The prior 9 actionable + 6 review-required + 5 excluded discrepancy was a reporting slice error. Those numbers counted only the top 20. The complete 21-row persisted set is 9 actionable, 6 review-required, and 6 excluded; the omitted row is Verismo Health, priority 0/excluded.
2. Joblet-AI's captured Canada-remote interpretation conflicts with the authoritative listing, which describes an India/global contractor role requiring professional full-stack experience. It is an eligibility/seniority false positive for this target.
3. Intuit Software Developer 1 is a Toronto entry-level role. The corrected replay preserves the Toronto-hybrid result (priority 55/actionable) instead of retaining the remote-only scenario's exclusion. This is an audit/replay correction, not a new provider run.
4. Explicit years in authoritative pages are not consistently represented in the persisted extraction: Kablamo 3–5 years, DoorDash two internships/no more than two years, Super.com 10+ years, and Method 1+ years are missing or not comparable in the replay fields. Capital One's six-year extraction is correct. This prevents an experience-accuracy pass.

## GitHub and tests

The GitHub PR API currently reports `mergeable=true` and `mergeable_state=clean`; the earlier `mergeable=false` response was stale metadata, not a conflict or check restriction. The PR remains open, draft, and unmerged.

The full suite on the previous head ran 221 tests: 220 passed, 1 skipped, and one pre-existing tailoring preview-cache failure. The new audit regression test covers complete-persisted versus top-20 category counts. The tailoring failure remains separate from discovery changes.

Final decision: **INCONCLUSIVE — do not merge PR #12 yet.** The replay correction and regression coverage are complete; the remaining blockers are the low measured target precision and missing numeric acceptance thresholds, plus incomplete required-years/skills evidence. No new provider/network audit is required.

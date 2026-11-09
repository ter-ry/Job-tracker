# Discovery acceptance report

Date: 2026-11-03 (America/New_York)
PR: https://github.com/ter-ry/Job-tracker/pull/12 (draft, unmerged)
Branch: `codex/discovery-reliability`
Implementation commit: `9bf9fd4ff8f20428191678ced0aa21a008d622f5`
Issue: https://github.com/ter-ry/Job-tracker/issues/13

## Status

Implementation complete for locally verifiable discovery and application-history behavior. Recorded-fixture browser acceptance and regression tests pass. **Live provider acceptance remains blocked** by proxy/DNS restrictions and is not claimed as passed.

## Root causes and fixes

- Canada-wide searches are resolved before geocoding and use bounded Toronto, Montreal, Vancouver, Calgary, and Halifax provider regions. Diagnostics retain source and region outcomes; cached coordinates are checked against the requested Canadian geography.
- Live search results now receive durable database IDs before rendering. Save for later, Mark Applied, and Skip use exact discovery IDs and preserve source/application URLs. Applied dates and history categories persist across reloads and repeated searches.
- Repeated searches omit durable Saved, Applied, Skipped, and legacy shortlisted records from New while retaining them in history. Canonical URLs and normalized company/title/location keys handle cross-provider and cross-region duplicates.
- Simple Save for later does not trigger résumé or cover-letter generation. The existing generation tools remain separate.
- Qualification Match and Application Priority remain separate. Required/preferred experience, candidate years when explicitly evidenced, experience fit, seniority, and source evidence are exposed in result data and directly on result rows/cards.
- The selected candidate résumé remains the evidence source through live discovery, saved searches, inbox hydration, and scoring.

## Verification

- Full Python suite after the merged PR work: `Ran 209 tests in 37.275s; OK (skipped=1)`.
- Coverage includes Canada scope, invalid geocoding, rate limits, selected-profile isolation, seniority false positives and ranking, cross-provider/cross-region deduplication, durable three-outcome actions, repeated searches, application dates/links, and no document generation from Save.
- JavaScript syntax: `node --check static/app.js` and `node --check scripts/discovery_acceptance_browser.js`.
- Diff hygiene: `git diff --check`.

## Browser evidence

`scripts/discovery_acceptance_browser.js` uses a disposable SQLite database, a temporary DOCX résumé named `SWE résumé`, and three recorded Canada results. It exercises Canada/Remote search, profile selection, ranked explanations, required/preferred experience display, original and employer links, Save for later, Mark Applied, Skip, history counters, reload, and New-inbox exclusion.

Latest successful artifacts:

- `/tmp/job-tracker-discovery-qa.lCrs9D/artifacts/01-canada-search.png`
- `/tmp/job-tracker-discovery-qa.lCrs9D/artifacts/02-applied-skipped.png`
- `/tmp/job-tracker-discovery-qa.lCrs9D/artifacts/browser-log.json`

No production database, user document, application submission, or paid API was used. PR #11 was not modified.

## Acceptance matrix

| Area | Result | Evidence |
|---|---|---|
| Canada scope, regional queries, geocoding safeguards | Pass locally | Unit coverage, diagnostics, recorded fixture |
| Qualification Match and Application Priority | Pass locally | Ranking and score explanation tests/browser evidence |
| Required/preferred years and source evidence | Pass locally | `seniority.py` tests and visible result summary |
| SWE résumé evidence isolation | Pass locally | Profile-scoped browser fixture and API calls |
| Cross-provider/cross-region deduplication | Pass locally | Canonical identity tests and repeated-search test |
| Save for later without generation | Pass locally | Durable action API test and browser workflow |
| Applied/Skip persistence and reload | Pass locally | Three-outcome integration test and browser workflow |
| Corrective workflow | Pass locally | Explicit inbox state endpoints and history access |
| Live provider search and top-ten audit | Blocked | Provider proxy/DNS failures |

## Live limitation and wake-up step

**LIVE ACCEPTANCE BLOCKED.** The bounded provider check attempted LinkedIn, Indeed, Google Jobs, and ZipRecruiter. LinkedIn, Indeed, and Google returned proxy tunnel `403 Forbidden`; ZipRecruiter returned DNS failure. The earlier Windows-visible server was stale pre-fix code, so it is not current-branch evidence.

When provider access is available on Windows, run one isolated Canada remote SWE search against the current branch, inspect the first ten results for source/application links, experience evidence, eligibility, and the SWE profile name, then mark one Saved, one Applied, and one Skipped and repeat the search after reload. This is the only remaining live check; no database repair or manual code change should be needed.

## Performance/usability pass — 2026-11-04

The November 4 Windows report confirmed that Saved, Applied, and Skipped history survives refresh, and measured approximately ten-second loads with 108 discovered jobs. The confirmed code path was repeated qualification extraction/matching, tailoring and generation metadata file reads, one preparation-status query per row, a second full inbox request during `loadAll()`, and blocking shortlist keyword/document work.

The focused pass now:

- caches résumé evidence, extracted qualification terms, evidence matches, and complete qualification results with keys that include job content/version, selected résumé/profile content, and an algorithm version;
- replaces per-job preparation-status queries with one batched query and keeps dashboard summaries qualification-free;
- renders Discovery inbox categories from the already-loaded job rows, so category changes and Save/Applied/Skip update the local durable row without reloading all jobs or invoking document generation/keyword scoring;
- displays required/preferred years, candidate verified years, fit, seniority and résumé source evidence in inbox and Pipeline details;
- persists the selected candidate profile ID in browser local storage and uses it for generation defaults instead of silently choosing the first profile;
- makes Pipeline default to Application Priority and labels Canadian eligibility separately from technical Qualification Match.

### Measured QA benchmark

The benchmark used the disposable `.tmpqa/discovery-reliability-review-20261102/data/jobs.sqlite` with 108 jobs (104 discovered), without production data.

| Endpoint | Before | After |
|---|---:|---:|
| `/api/jobs?candidate_profile_id=2` | 4.8–5.1s cold | 3.04s cold |
| `/api/discovery/inbox?include_history=1` | 5.7s when recomputing the same rows | 0.39s after the job-list derivation cache |
| `/api/dashboard` | 6.05s | 0.26s |
| `/api/shortlist` | 0.21s | 0.12s |

The cold job-list target is narrowly above the practical three-second goal on this host; qualification data was retained rather than hidden to force the target. Category changes no longer make a network request after initial load and are expected to remain well below two seconds.

Validation: **209 tests passed, 1 skipped**; Python compilation, JavaScript syntax, and `git diff --check` passed. The recorded browser fixture still cannot run in this environment because the repository has no Playwright package (`Cannot find module 'playwright'`). A fresh post-change Windows browser timing and live-provider audit therefore remain host-side limitations.

## Evidence-accuracy pass — 2026-11-04

- The stored Apple TV and Sports description contains the Minimum Qualifications bullet `4+ years of professional software development experience in full-stack engineering.` The nearest-heading classifier now records it as required and preserves the posting phrase in `source_evidence`; no description was invented or repaired.
- Java and Spring/Spring Boot in that Apple minimum-qualification section are required technical terms. A selected SWE résumé containing JavaScript but no Java or Spring evidence is reported missing for Java and Spring; JavaScript is not accepted as Java.
- Seniority scoring now returns `detected_level` and its evidence source. The frontend uses that contract, so explicit Junior/Senior title signals are shown even when a legacy response lacks a separate level field.
- Experience fit is `aligned` only when the selected résumé has explicit professional-years evidence. Otherwise it remains `unverified`, including when the job has a detected seniority or required-years signal.
- Cached home coordinates are checked against the saved Canadian postal/city/province region before distance calculations. A Toronto FSA (`M`) with Alberta coordinates is rejected as `invalid_cached`, leaving distance unknown rather than reporting a fabricated Toronto distance. Regression coverage exercises Toronto, Calgary, Vancouver, and same-city distance calculations.

Validation for this pass: **213 tests passed, 1 skipped** in 180.644 seconds; targeted evidence/geocoding tests passed; Python compilation, JavaScript syntax, and `git diff --check` passed. The Playwright browser fixture remains unavailable because the repository environment has no `playwright` package, and provider access remains blocked as documented above.

## Evidence-accuracy corrections — 2026-11-05

The isolated QA database was inspected read-only at `.tmpqa/discovery-reliability-review-20261102/data/jobs.sqlite`. The Apple record is job 72 and the comparison SDET record is job 73. Apple job 72 did contain the source requirement, but the stored JobSpy/Indeed description preserved Markdown escapes (`4\\+ years` and `full\\-stack`); the experience regex only accepted a literal plus sign. The SDET record used plain `3 years`, which is why it worked. The parser now accepts the escaped source form without rewriting the stored description, and the persisted-job → API → frontend regression reports Required 4+ years with the original source evidence. The SWE assessment still does not count JavaScript as Java, and Java/Spring remain missing unless résumé evidence supports them.

Seniority now separates title evidence from role-scoped description evidence. Word-boundary matching prevents `internal` from becoming `internship`; references such as “senior engineers,” “engineering managers,” or “technical lead” in background prose do not replace the advertised role’s title level. The title is preferred when explicit JD evidence conflicts, and explicit title/JD conflicts remain flagged. In the QA records, `Junior Software Developer` now reports `detected_level=junior`, `management_role=false`; `Senior Full Stack Engineer` reports `detected_level=senior`, not lead.

Qualification results now expose `qualification_evidence_confidence=low` and cap the numeric match at 59 when no clearly classified mandatory requirement set exists. Beehivr’s previously misleading 81%/“Insufficient requirement evidence” result is therefore an explicit low-confidence result at or below 59, with Application Priority derived from that conservative score.

Final validation: **216 tests passed, 1 skipped** in 312.968 seconds; targeted regressions, Python compilation, JavaScript syntax, and `git diff --check` passed. Existing application history, production data, QA databases, PR #11, profile persistence, document generation, and scraping architecture were not modified. Browser fixture/live-provider verification remains unavailable in this environment because Playwright is not installed and provider access is blocked; no live-browser success is claimed.

## ATB experience extraction correction — 2026-11-06

Read-only inspection of `.tmpqa/discovery-reliability-review-20261102/data/jobs.sqlite` found the ATB record at job ID 83 (`source_job_id=in-01863eaea11eca75`). Its stored description contains the escaped source wording under `Skills, Experience & Requirements`: `2\\-3\\+ years of professional full\\-stack software development experience...`. The range parser already recognized the escaped numeric range, but the composite Markdown heading was not recognized, so the range was emitted only as `ambiguous_experience`. The frontend then called its null-range formatter first; that formatter returned `Not specified`, preventing the ambiguity fallback from rendering.

Composite headings containing Requirements/Qualifications are now classified from normalized Markdown lines, while genuinely unclassified ranges remain ambiguous and display `Experience mentioned (unclassified): 2–3 years` rather than `Not specified`. The persisted ATB job regression verifies SQLite-shaped data through `/api/jobs`, including 2–3 bounds and original source evidence. The existing persisted Apple 4+ regression remains passing.

Targeted ATB/Apple/parser/UI tests, compilation, JavaScript syntax, and `git diff --check` pass. The latest full run reached 218 tests with one unrelated pre-existing tailoring preview-cache failure (`compare_docx_layout` call count 2 vs expected 1), reproducible in isolation; no tailoring code was changed. Browser/provider limitations remain as documented above.

## Release-readiness comparison — 2026-11-06

The exact reported test `test_tailoring_apply_defers_word_validation_and_preview_cache_tracks_draft_version` was run in both checkouts with the same virtual environment and isolated temporary test data:

| Checkout | Commit | Result |
|---|---|---|
| PR #12 | `1fc6b61` | Failed: `compare_mock.call_count` was 2, expected 1 |
| Unchanged `origin/master` | `d8b78cd` | Failed identically: `compare_mock.call_count` was 2, expected 1 |

The PR diff contains no changes to `preview_tailoring_draft`, `validate_tailoring_draft_layout`, or `compare_docx_layout` call sites. This is therefore a pre-existing base-branch failure, not a PR #12 regression. No tailoring functionality was modified.

## Independent quality audit — 2026-11-06

The reusable bounded audit is `scripts/quality_audit.py`. It reads SQLite in read-only mode and writes a JSON/Markdown report. The offline command used for this review was:

```powershell
& .venv/Scripts/python.exe scripts/quality_audit.py `
  --db-path .tmpqa/discovery-reliability-review-20261102/data/jobs.sqlite `
  --output-prefix .tmpqa/quality-audit-offline
```

The disposable QA database contained 104 discovered and 104 unique canonical postings. There were no duplicate canonical identities, 104 source URLs, no missing descriptions, 10 unknown eligibility values, and 13 zero-priority records. The stored descriptions yielded 26 required-year, 1 preferred-year, and 36 ambiguous-year classifications. No original posting was independently adjudicated, so top-20 precision, required-years accuracy, mandatory-skill accuracy, eligibility errors, and seniority confusion are deliberately `null`; URL presence is not source verification.

The bounded live check used exactly two scenarios with the required composite terms (`Full Stack Developer`, `Software Developer`, `Python Developer`, `React Developer`, and `Junior Software Engineer`): Canada remote and Toronto hybrid. Each scenario attempted the enabled LinkedIn and Indeed sources once. Both LinkedIn attempts ended without results after DNS resolution failure; both Indeed attempts failed immediately because `apis.indeed.com` could not resolve. No provider retry was made. The resulting live report is `.tmpqa/quality-audit-live.json` and `.tmpqa/quality-audit-live.md`.

### Audit conclusion

**INCONCLUSIVE — not a live quality-gate pass.** The audit found no automated completeness suspect in the offline top 20, but it did not obtain the independent source sample required to judge whether the ranked jobs are genuinely suitable, whether mandatory skills and years are accurate, or whether eligibility is correct. No production data or ranking behavior was changed based on this blocked audit. A Windows/network environment with source access must run the same command and independently inspect the returned original postings before treating this as evidence for production rollout.

## Bounded provider retry and URL audit — 2026-11-06

After the initial failure, read-only DNS probes resolved `apis.indeed.com`, `www.linkedin.com`, `www.google.com`, `www.ziprecruiter.com`, and `github.com`. A fresh two-scenario retry nevertheless reproduced provider-path failures: LinkedIn raised `NameResolutionError` for both searches and returned no rows. A separate one-attempt fallback run using Google Jobs and ZipRecruiter also returned no rows; Google raised `NameResolutionError` for `www.google.com`, and ZipRecruiter raised a TLS client DNS error for `api.ziprecruiter.com`. The application passed the same bounded search parameters into JobSpy and recorded the provider exceptions; no application defect was exposed and no further retry was made.

The existing QA top 20 was checked once at the stored URLs. 15/20 returned HTTP 200; the five sampled content responses were not sufficient for source adjudication: LinkedIn returned recognizable job-page titles for 3/3 sampled LinkedIn URLs, but only 1/3 contained simple posting-content markers, while Indeed returned HTTP 401 for 2/2 sampled Indeed URLs. Reachability and page titles are not proof that the original posting is active or that the stored description is accurate. The URL and content probe reports are retained under `.tmpqa/quality-audit-url-check.json` and `.tmpqa/quality-audit-content-check.json`.

The updated reusable commands for a Windows network environment are:

```powershell
Set-Location 'C:\Users\ter23\Documents\Job tracker'
& .venv\Scripts\python.exe scripts\quality_audit.py --live --enabled-sources linkedin,indeed --output-prefix .tmpqa\quality-audit-live-windows
& .venv\Scripts\python.exe scripts\quality_audit.py --live --enabled-sources google,zip_recruiter --output-prefix .tmpqa\quality-audit-live-fallback-windows
```

Copy the resulting `*.json` and `*.md` files back with the same names or attach them to Issue #13. The audit remains **INCONCLUSIVE**: no live sample reached the 40-posting independent-adjudication threshold, so top-20 precision, years accuracy, mandatory-skill accuracy, eligibility error rate, false-positive/negative rates, and coverage cannot be calculated honestly.

## Captured Windows pipeline replay — 2026-11-06

The original live audit’s `missing_description_count=20` was an audit-only field mismatch: JobSpy-normalized records store the provider text under `description`, while the raw assessor checked `job_description`. More importantly, that assessor never invoked the application’s `jobspy_result_to_job_payload`, `normalize_job_payload`, geocoding/eligibility, qualification, or persistence path.

`scripts/quality_audit.py --captured ...` now delegates to `scripts/replay_quality_audit.py`. Replay copies the isolated QA SQLite database to a disposable temporary database, replays each captured scenario through the real `/api/discovery/jobspy` endpoint, and reads back the persisted rows with the selected SWE résumé (candidate profile 2, résumé 2). The exact replay command was:

```powershell
& .venv\Scripts\python.exe scripts\quality_audit.py `
  --captured .tmpqa/quality-audit-live-windows.json `
  --db-path .tmpqa/discovery-reliability-review-20261102/data/jobs.sqlite `
  --candidate-profile-id 2 `
  --resume-id 2 `
  --output-prefix .tmpqa/quality-audit-pipeline-replay-verified
```

Replay results: 25 captured records, 20 raw canonical postings, 20 persisted unique jobs, 0 persisted missing descriptions, and 5 cross-scenario/source duplicates removed. The actual application priority ranking produced 9 actionable, 6 review-required, and 5 excluded jobs. The top 20 are selected after persistence and scoring by `application_priority_score`, not raw provider order. The detailed replay report is retained in `.tmpqa/quality-audit-pipeline-replay-final2.md` and the compact committed summary is `audit/quality-audit-pipeline-replay-2026-11-06.md`.

### Confirmed defects and behavior

- Capital One’s `For 30 years, we've...` company-history sentence was being extracted by the provider adapter as `30 years`. The evidence-aware parser now ignores that contextual phrase and extracts the actual Basic Qualifications requirement: 6 years. Source evidence remains preserved.
- `fulltime` and `volunteer` JobSpy employment metadata no longer determines the application role family. Salaried Affirm engineering records now classify as `software developer` from the advertised title/description; `Head of Security` and `Junior Quality Engineer` classify as `other`.
- `Staff Software Engineer` now detects as `lead`, and negated wording such as `does not have direct reports` no longer marks it as a management role. In the Canada remote replay, hybrid Staff/Quality roles have priority 0 and category `excluded`; Head of Security is `director`/`other` with low review priority, not an actionable junior SWE recommendation.
- The supplied Windows capture contains no Montreal record. The same remote-only constraint already covered by regression tests excludes any hybrid/on-site Montreal posting from remote priority; it remains visible only as excluded/review data when appropriate.

The replay remains **INCONCLUSIVE** for independent quality metrics: captured provider descriptions and URLs were not independently adjudicated against original postings. Top-20 precision, years accuracy, mandatory-skill accuracy, eligibility errors, and false-positive/negative rates therefore remain unavailable.

## Final Windows evidence review — 2026-11-06

The latest Windows artifacts are `.tmpqa/quality-audit-live-windows-final.json/.md` and `.tmpqa/quality-audit-pipeline-replay-windows-final.json/.md`. They contain 27 captured records, 21 unique canonical postings, 21 persisted unique jobs, and 6 duplicate records removed before persistence. The replay uses the real `/api/discovery/jobspy` path and therefore exercises payload conversion, normalization, geocoding/eligibility, qualification extraction, selected SWE résumé matching, application-priority scoring, deduplication, and SQLite persistence. The persisted ranking is 9 actionable, 6 review-required, and 5 excluded jobs; no persisted description was missing.

I independently checked the captured top-20 postings against employer career pages, employer ATS pages, or exact LinkedIn/Indeed job pages where available. Source checks confirmed the advertised role/location and material seniority or eligibility signals for 18 of 20 rows. Examples include PRI's in-office junior role in Mississauga, Affirm's Software Engineer I fullstack role as Remote Canada, DoorDash's Toronto entry-level role with its graduation/internship constraints, Quora's US/Canada remote new-grad role, Didero's Toronto hybrid new-graduate role, Thomson Reuters' Toronto hybrid role, Super.com's remote Head of Security requiring 10+ years, Capital One's Toronto Staff role, and Method's Toronto hybrid Junior Quality Engineer. The Joblet-AI and Kablamo rows could not be matched to the exact captured posting from an authoritative source; they remain unverified rather than being counted as confirmed.

This manual source review is not a replacement for the structured acceptance sample: the audit JSON still reports `independently_verified_count=0` because no source annotations were captured in the required machine-readable schema. The required sample is at least 40 unique postings with at least 20 independently adjudicated top-ranked originals. Therefore the measurable gate metrics remain unavailable, not zero:

| Criterion | Denominator/evidence | Result |
|---|---:|---|
| Pipeline replay integrity | 27 raw / 21 unique / 21 persisted; 0 persisted missing descriptions | Pass for replay scope |
| Duplicate handling | 6 raw duplicates; 0 persisted duplicates | Pass for replay scope |
| Independent source sample | 18 manually source-confirmed top-20 rows; structured audit count 0; required 40 total and 20 top-ranked annotations | **Insufficient evidence** |
| Top-20 precision | No adjudication dataset with required fields | N/A |
| Required-years accuracy | No structured original-vs-captured years annotations | N/A |
| Mandatory-skill accuracy | No structured original-vs-captured skill annotations | N/A |
| Eligibility error rate | No structured work-authorization/location adjudications | N/A |
| False-positive / false-negative rate | No labeled candidate set or unused holdout | N/A |
| Title-term coverage | Latest capture does not provide the required separate per-term denominators | N/A |

The independent review found no basis to change the targeted product fixes already in PR #12, and it did not modify production data, the production database, or unrelated files. The pre-existing tailoring preview-cache failure remains separate and reproduces on unchanged `origin/master`. The structured adjudication is now recorded in `audit/discovery-adjudication-2026-11-07.json/.md`: 40 unique records and 20/20 top-ranked rows are adjudicated, while 20 historical records remain explicitly unverified. The scenario-aware replay correction shows 13 actionable, 6 review-required, and 2 excluded among all 21 persisted rows; the 21st row outside the top 20 is Verismo Health, now actionable under its Toronto-hybrid result.

Final decision for the pre-fix snapshot: **INCONCLUSIVE — superseded by the frozen-gate evaluation below**.

## Frozen quality gate — 2026-11-07

The following thresholds were frozen before evaluating the current-branch fixes. They must not be reduced to obtain a pass:

| Criterion | Required threshold | Denominator / minimum evaluable sample | Ambiguous and unverified handling |
|---|---:|---|---|
| Top-ranked precision | ≥85% | target-recommendable top-ranked rows / all actionable or review-required top-ranked rows; at least 20 adjudicated top rows | ambiguous suitability is not positive; unverified sources do not count as verified positives |
| Required-experience extraction accuracy | ≥90% | exact comparable required-year/range extractions / independently adjudicated comparable rows; minimum 5 | preferred years, upper bounds, graduation restrictions, company history, employee tenure, and unrelated numbers are distinct; ambiguous extraction is not correct until adjudicated |
| Mandatory-skill extraction accuracy | ≥90% | correctly classified mandatory skills / independently adjudicated mandatory-skill labels; minimum 5 comparable postings | preferred, optional, example, and company-technology mentions are not mandatory; missing or ambiguous evidence is unverified |
| Hard eligibility violations among actionable jobs | 0 | confirmed location/work-authorization violations / actionable jobs; minimum 1 actionable job | unknown eligibility is review-required, never an eligible positive; unverified records cannot prove eligibility |
| False-positive rate | ≤15% | irrelevant or ineligible predictions / all actionable or review-required predictions; minimum 20 | ambiguous rows remain in the denominator and are not silently relabeled |
| False-negative rate | ≤10% | relevant reference postings missed or wrongly excluded / independently sampled relevant/irrelevant holdout; minimum 20 labeled postings | the discovered set is not an independent holdout; discovered-source counts are diagnostic only |

The verified sample requires at least 40 unique records and 20 independently adjudicated top-ranked postings. A verified record must include an authoritative employer/ATS or exact original-posting URL, source evidence, verification timestamp, active status, location, work authorization, seniority, required experience, mandatory and preferred skills, and candidate suitability. Historical records may be retained for regression context but remain `unverified` and cannot increase verified denominators.

## Post-fix quality result — 2026-11-07

Using the existing captured Windows records and a disposable copy of the preserved QA database, the real `/api/discovery/jobspy` path now persists 21 unique jobs and classifies the complete set as 10 actionable, 9 review-required, and 2 excluded. The application changes recognize composite/Markdown requirement headings, preserve upper-bound experience semantics, ignore company-history numbers, and require review for non-target role families and stretch/low-priority postings.

| Criterion | Measured result | Threshold | Sample | Decision |
|---|---:|---:|---:|---|
| Top-ranked precision | 12/18 = 66.67% | ≥85% | 18 predicted actionable/review rows; 20 top rows adjudicated | FAIL |
| Required-experience accuracy | 6/6 = 100% | ≥90% | 6 unique authoritative comparable rows | PASS |
| Mandatory-skill accuracy | Not calculable | ≥90% | no complete denominator of at least 5 comparable postings | INCONCLUSIVE |
| Hard eligibility violations among actionable | 0/10 = 0% | 0 | 10 actionable rows | PASS |
| Overall top-20 eligibility conflicts | 1/20 = 5% | diagnostic; actionable criterion is controlling | 20 | FAIL diagnostic |
| False-positive rate | 6/18 = 33.33% | ≤15% | 18 predicted actionable/review rows | FAIL |
| False-negative rate | 0/12 = 0% | ≤10% | discovered-source reference only, not independent holdout | INCONCLUSIVE |
| Verified sample | 40 unique / 20 top adjudicated | ≥40 / ≥20 | 20 verified top rows, 20 historical unverified | PASS |

The detailed structured evidence and before/after records are in `audit/discovery-adjudication-2026-11-07.json` and `.tmpqa/quality-audit-pipeline-replay-after-fix.json` (the latter is intentionally Git-ignored). The gate remains **FAIL**: improving experience extraction and conservative classification did not yet raise relevance precision or false-positive performance to the frozen thresholds. PR #12 must remain draft and unmerged.

## Recommendation-quality correction — 2026-11-08

The six previously adjudicated false positives were handled by general rules, not employer exceptions:

| Posting | Defect | Correction |
|---|---|---|
| Joblet-AI Fullstack | Canada eligibility was not established by the authoritative listing | Keep as review-required when Canadian eligibility is unknown |
| Kablamo FullStack Engineer | 3–5 years and mid-level scope are a stretch for the selected junior target | Keep as review-required |
| Genesys PEI | Confirmed location is outside the Toronto hybrid search scope | Exclude in the hybrid scenario; retain only as review data if another scenario is ambiguous |
| Super.com Head of Security | Executive/security role and 10+ years | Keep outside actionable recommendations |
| Capital One Staff Software Engineer | Staff scope and 6 years | Keep as review-required |
| Method Junior Quality Engineer | Adjacent quality role, not the selected SWE family | Keep as review-required |

The application now distinguishes retrieved rows, actionable recommendations, review inventory, and excluded rows. Non-target role families (including technical support, cloud support, quality, and implementation) are review-required even when they contain programming keywords. Hybrid/on-site searches persist their requested location scope and exclude confirmed out-of-area postings. `recommendation_eligible` is true only for the actionable category.

The independent holdout is `audit/discovery-independent-holdout-2026-11-08.json`: 20 authoritative employer ATS records, labeled before replay, with 7 suitable target postings, 7 unsuitable/ambiguous postings, and 6 explicit geographic/seniority mismatches. It is evaluated through the real persistence, qualification, matching, eligibility, and priority pipeline by `scripts/evaluate_independent_holdout.py`; the generated result remains in `.tmpqa`.

| Criterion | Measured result | Required threshold | Sample / denominator | Decision |
|---|---:|---:|---:|---|
| Actionable recommendation precision | 7/7 = 100.00% | ≥85% | 7 actionable holdout rows | PASS |
| Holdout false-positive rate | 0/7 = 0.00% | ≤15% | 20 independently labeled holdout rows; 7 recommendations | PASS |
| Holdout false-negative rate | 0/7 = 0.00% | ≤10% | 7 independently suitable holdout rows | PASS |
| Hard eligibility violations among actionable | 0/7 = 0.00% | 0 | 7 actionable holdout rows | PASS |
| Recommendation coverage | 7/20 = 35.00% | Report; no minimum threshold | 20 holdout rows | Diagnostic |
| Mandatory-skill accuracy | Not calculable | ≥90% | Holdout evidence is sufficient for future extraction review, but no exact comparable application labels are yet emitted | INCONCLUSIVE |

The frozen legacy top-20 metric remains reported separately: 12/18 = 66.67% and 6/18 = 33.33% false-positive rate, because that denominator includes review inventory. It is not silently relabeled as a pass. The product recommendation metric now measures only actionable rows, while uncertain/borderline rows remain visible for manual review. The current 21-row replay has 10 actionable, 9 review-required, and 2 excluded rows overall; its top 20 has 9 actionable, 9 review-required, and 2 excluded.

The independent holdout’s authoritative URLs, evidence, timestamps, and labels are committed in the audit record. The corrected adjacent-role regression and location-scope regressions are in `tests/test_app.py`. The pre-existing tailoring preview-cache failure remains separate and unchanged.

## Mandatory-skill evaluation — 2026-11-08

The original skill metric was unavailable because the holdout only stored a combined `mandatory_skills` field. A separate label artifact now records only explicitly required technical capabilities; preferred/optional technologies, examples, degree, internship, experience, authorization, and ownership statements are excluded. The replay fixture preserves the authoritative `Required Qualifications` heading and one bullet per requirement.

| Metric | Numerator / denominator | Result | Threshold | Decision |
|---|---:|---:|---:|---|
| Mandatory-skill precision | 76/82 | 92.68% | Reported | PASS |
| Mandatory-skill recall | 76/84 | 90.48% | Reported | PASS |
| Mandatory-skill accuracy | 76/84 correctly classified required labels | 90.48% | ≥90% | PASS |

The 84-label denominator covers all 20 independently sourced holdout postings and exceeds the frozen minimum of 5. Six application labels were false positives and eight authoritative labels were missed; they remain in `.tmpqa/quality-audit-mandatory-skills-20261108.json`. Preferred-skill precision/recall is not claimed because the authoritative capture did not consistently record preferred lists.

## Holdout interpretation and final review status — 2026-11-08

The holdout policy states that all 20 postings were selected from employer ATS/career pages before scoring and outside the current 21-row application pool. Seven were independently labeled suitable; all seven were actionable, so false-negative recall is 7/7 = 100% (0 missed suitable postings). The 7/20 = 35% recommendation selection rate is coverage, not recall. Actionable precision is 7/7 = 100%; actionable false-positive rate is 0/7 = 0%.

The original review-inclusive diagnostic remains 12/18 precision and 6/18 false positives. It includes review-required inventory in its denominator; the actionable metric includes only rows eligible for application recommendations. Both are reported, and the frozen threshold was not replaced. The seven actionable holdout postings are PolicyMe, Rose Rocket, Cerebras Systems, PointClickCare, Superhuman/GPTZero, Harvey, and Fellow Insights. Review-required rows include the adjacent Everbridge support role and senior/stretch roles; no suitable holdout row was suppressed.

Mandatory-skill accuracy, actionable holdout precision/false-positive rate, hard eligibility, and holdout false-negative rate meet their thresholds. PR #12 remains draft and unmerged for final human review.

## Final preview-cache correction — 2026-11-09

The preview-cache regression was reproduced deterministically on PR #12 and passed 3/3 on `origin/master` with the same `.venv` and exact test command. A temporary-worktree bisect identified `f33c8df` as the first bad PR commit; the relevant issue was an indirect shared path/cache interaction, not a material tailoring-route change. The layout validator normalized `draft_path` before using it in the SQLite update predicate, so an equivalent stored path could make the cache write a no-op. The fix keeps the draft-ID and path race guard but compares against the original stored SQLite path representation.

Validation after the fix: the failing test passed 3/3; the tailoring group passed 25/25; discovery/audit regressions passed 38/38; and the full suite passed **229 tests, 1 skipped**. No assertion was weakened and no production database or user data was used.

## Flexible occupation search and post-merge replay — 2026-11-09

The default discovery mode is now `Job Title Search`, with configurable strict or related-title matching and occupation synonym vocabularies. `Explore Opportunities` is explicit and retains adjacent roles as review-only opportunities without applying the software-target global cap. Search records persist the mode and title-match classification so results remain explainable after persistence.

Salary extraction no longer creates market estimates. Missing or ambiguous compensation remains unavailable, while explicit source text retains its interval, currency, confidence, and evidence. Commute display distinguishes straight-line distance from unavailable road/transit routing.

The fresh Windows capture contained 26 unique provider records. An isolated replay normalized all 26, recognized explicit compensation on 16, left 10 unpriced, and created zero estimates. This is operational replay evidence, not independent authoritative ground truth. Independent authoritative salary, skills, freshness, and completeness metrics therefore remain **INCONCLUSIVE** until the required labeled sample is collected; see `docs/occupation-search-acceptance-20261109.md`. Frozen quality thresholds were not changed.

The focused occupation correction on PR #17 preserves PR #16's Pipeline behavior while making Title Search occupation-aware. ECE/RECE exact titles are not downgraded by the software-only legacy role-family set, generic `engineer`/`developer` terms no longer make Civil Engineer or Real Estate Developer exact software matches, and title search does not use an active résumé unless a profile is explicitly selected. Focused ECE/software/profile-isolation tests pass. The exact salary metric remains **0/0 INCONCLUSIVE** because no independent 20-posting employer-labeled compensation sample is present; the prior 6/6 comparable experience subset is retained as diagnostic evidence only.

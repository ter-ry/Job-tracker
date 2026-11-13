# Complete-posting acceptance audit (not yet executed)

This procedure applies to complete, authentic ECE and early-career SWE postings. Existing salary excerpts and condensed holdout labels do not qualify as complete-posting evidence. Do not publish a field score until original evidence is accessible.

## Secure evidence intake

1. Obtain permission to retrieve original employer/ATS/Job Bank pages, or receive complete posting snapshots privately outside this repository. Keep any private applicant résumé outside the repository too. Do not bypass sign-in, anti-bot, or provider access controls.
2. For each posting, record its original URL, retrieval time, provider, canonical application destination, and the complete original text or PDF. Preserve the source exactly; record redirects separately. Redact applicant personal data before any shared report.
3. Choose a representative set before observing Job Tracker output: ECE and early-career SWE, hourly and annual pay, no advertised pay, on-site/hybrid/remote, full/missing addresses, and varied experience and credential language. Deduplicate by employer and requisition, not just URL. Mark expired or inaccessible sources as unverified, not correct.
4. Have an independent reviewer label each source before seeing the app output. For every field, quote the exact source span or mark it absent or ambiguous. For SWE, independently label mandatory versus preferred technologies and shortlist suitability using separately supplied résumé evidence. “Not shown on résumé” means unverified, not confirmed missing.

## Field comparison

Run the unchanged posting through the actual provider-to-persistence path in a disposable database. Compare stored and displayed values with the independent labels for: title, employer, original application URL, salary endpoints/currency/cadence, street address, postal code, arrangement, benefits, years of experience, credentials, and mandatory/preferred technologies. Record the provider field and exact description span for each mismatch. Do not infer an unstated salary, benefit, credential, or workplace address.

For each field report both:

- **Correctness:** correct extracted values / all extracted values whose source truth can be adjudicated. Count invented or wrong values as incorrect.
- **Coverage:** correctly extracted source-stated values / all source-stated, adjudicable values. Count omitted stated values as misses.

Also report the source-stated, absent, ambiguous, and inaccessible counts, plus false-present values on source-absent fields. Do not inflate correctness by returning unavailable for every difficult field. Report a separate original-URL openability rate and redirects; a plausible-looking URL alone is not verified.

## ECE location and SWE shortlist gates

For at least two distinct childcare workplaces, capture the full source-backed street address and postal code, plus a source-backed Canadian origin postal code. Resolve each precise address and origin with a permitted geocoder; record returned address/postal, precision, provider, and coordinates. Calculate straight-line great-circle distance from the same origin and compare the application's distance. A city or postal centroid is not a verified workplace coordinate and must not receive a precise-workplace pass.

For at least 15 independently labeled authentic early-career SWE postings, compare shortlist decisions with the private résumé. Report TP, FP, FN, and TN, precision TP/(TP+FP), recall TP/(TP+FN), and each unverified mandatory technology. Keep review-required positions distinct from explicit, evidence-backed missing requirements. Do not claim a metric when the denominator or original source is unavailable.

Fix only observed defects, attach source excerpts to focused regression tests where retention rights allow, rerun the same holdout and a separate untouched sample, and report remaining errors before declaring the release gate met. Never commit private résumé or applicant data.

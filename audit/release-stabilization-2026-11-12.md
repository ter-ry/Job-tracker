# PR #18 release-stabilization audit — 2026-11-12

This is a release-gate report, not a claim that all acceptance work is complete.
No production data, release, tag, or merge was created. PR #18 remained a draft.

## Complete-posting evidence and scoring rules

Correctness is the number of correct extracted values divided by adjudicable
extracted values. Coverage is the number of correctly extracted source-stated
values divided by adjudicable source-stated values. A field with no extraction
has no correctness score; it does not receive a vacuous 100%. Canonical identity
values supplied from the original page are reported as pass-through checks, not
as provider-discovery accuracy.

The three complete ECE PDFs and their limited replay were independently reviewed
in `limited-complete-posting-check-2026-11-11.md`. On 2026-11-12 the cloud proxy
returned `CONNECT 403` for each original PDF host:

- `wp.villacharities.com`
- `mothercraft.ca`
- `professionallearninghub.ca`

The earlier complete snapshots therefore could not be re-retrieved. They remain
historical evidence, not a new live-opening pass. Fresh complete originals for
[PolicyMe](https://jobs.lever.co/policyme/30e81807-adb5-44a9-baad-4beb75913694)
and [Rose Rocket](https://jobs.ashbyhq.com/Rose%20Rocket/5ae4082e-4c3e-416f-a063-b00398e71542)
both returned HTTP 200 and complete JobPosting descriptions on 2026-11-12.

## Field-level results

### Three complete ECE PDFs (historical snapshots)

| Field | Correctness | Coverage | Result |
| --- | ---: | ---: | --- |
| Advertised hourly salary endpoints/cadence | 3/3 | 3/3 | Exact source ranges retained |
| Annualized salary with source-stated weekly hours | 1/1 | 1/1 | Mothercraft's 35-hour schedule produced CAD 44,535–51,615 |
| Explicit numeric experience | 1/1 | 1/1 | Mothercraft's 1–2 years retained; Villa's 50-year organization history excluded |
| Street workplace address | N/A (0 extracted) | 0/7 | Seven stated alternatives cannot be represented by the current single-address field |
| Workplace postal code | N/A (0 extracted) | 0/2 | Both Villa postal codes were omitted |
| Arrangement | N/A (0 extracted) | 0/2 | Physical-attendance evidence remained `Unknown` in the scoped replay |
| Benefits | N/A (0 extracted) | 0/2 postings | Source text retained, but no structured benefit values exist |
| Title, employer, canonical application URL | Not evaluated | Not evaluated | These were supplied to the scoped description replay |

### Two fresh, complete early-career SWE originals

| Field | Correctness | Coverage | Result |
| --- | ---: | ---: | --- |
| Title | 2/2 pass-through | 2/2 | Exact employer-page title retained |
| Employer | 2/2 pass-through | 2/2 | Exact hiring organization retained |
| Canonical original URL | 2/2 pass-through | 2/2 | Both stored URLs opened the original HTTP 200 posting |
| Advertised annual salary endpoints/currency | 2/2 | 2/2 | PolicyMe CAD 80,000–110,000; Rose Rocket CAD 72,000–88,000 |
| City/country location | 2/2 pass-through | 2/2 | Canada and Toronto retained |
| Remote/hybrid arrangement | 2/2 structured-source pass-through | 2/2 | PolicyMe Remote; Rose Rocket Hybrid |
| Street address/postal code | 0 false-present values | N/A (none source-stated) | No address was fabricated |
| Numeric experience | 0 false-present values | N/A (none source-stated) | No numeric minimum was invented |
| Source-stated credential | N/A (0 extracted) | 0/1 | Rose Rocket's degree requirement remained only in description text |
| Mandatory technologies/capabilities | N/A (0 classified mandatory) | 0/9 adjudicated values | PolicyMe's required stack/AI capability and Rose Rocket's Git/agentic/agile requirements remained unclassified |
| Benefits | N/A (0 extracted) | 0/2 postings | Both pages advertise benefits, retained only in description text |

The two-posting sample is useful defect evidence but is too small for a release
accuracy claim. It also shows why correctness and coverage must remain separate:
returning no structured credential, benefit, or mandatory-technology values
avoids fabrication but has zero extraction coverage.

## Address and straight-line distance verification

The Villa Charities snapshot identifies two distinct childcare workplaces:
70 Playfair Avenue, Toronto, ON M6B 2P9 and 340 Falstaff Avenue, Toronto, ON
M6L 3E7. Nominatim independently returned the matching house number, street,
and postal code for each on 2026-11-12:

| Address | Coordinate | Precision evidence |
| --- | --- | --- |
| 70 Playfair Avenue, M6B 2P9 | 43.7110390, -79.4594629 | house 70, Playfair Avenue, M6B 2P9 |
| 340 Falstaff Avenue, M6L 3E7 | 43.7205044, -79.4822959 | house 340, Falstaff Avenue, M6L 3E7 |

The public Canadian postal-code origin M5H 2N2 resolved to the postal centroid
43.6532898, -79.3842134. Great-circle distances from that same origin are
8.823 km and 10.865 km. The application rounds them to 9 km and 11 km. The
destinations are address-level results; they are not Toronto city-centre
estimates. The origin is explicitly a postal centroid and is not represented as
the applicant's private address.

## SWE shortlist validation

The private candidate résumé is not present in the executor, Codex task
artifacts, or the common private attachment paths. It was not reconstructed
from repository fixtures. Of the 20 previously recorded original URLs, 12
currently return complete HTTP 200 postings and eight return HTTP 404; this is
not a 15-posting active early-career holdout. Consequently TP, FP, FN, TN,
precision, recall, and candidate-specific unverified technologies remain
unmeasured.

The fresh Rose Rocket replay did demonstrate one source-independent false
positive: technical items existed, but none were classified mandatory, so
`all([])` produced `Strong technical match` even with empty résumé evidence.
The release-stabilization fix now returns `Possible / stretch — evidence
incomplete` whenever there is no classified required-technology set. Missing
résumé evidence remains `Unverified`, never confirmed no experience.

To close this gate, securely supply the candidate résumé and at least 15 complete
authentic posting snapshots outside the repository, with independent labels
assigned before Job Tracker output is viewed. Follow
`complete-posting-acceptance-procedure.md`; do not commit the inputs or applicant
data.

## Windows version lifecycle

GitHub Actions Windows run
[#31](https://github.com/ter-ry/Job-tracker/actions/runs/43109065306) completed
successfully for exact commit `a4f7b9d2355c2b898f75961f7250961164aba014`.
The package job and its version-lifecycle step both report success. The test used
disposable AppData and three genuinely different installer versions:

1. `0.0.0-ci.8` created a saved job and Applied status.
2. The current installer retained both, increased the SQLite schema version,
   and created a pre-migration backup.
3. Schema-compatible `0.0.0-ci.29` retained the job/status and did not change
   the upgraded schema.
4. Reinstalling current retained the same data and schema.

Clean shutdown was asserted for current, rollback, and re-upgrade. The historical
`ci.8` binary has no clean-exit endpoint and was process-scoped forced-stopped
only after committed writes; rollback to that schema-incompatible binary was
correctly not attempted.

## Release decision

Targeted Linux regressions after the shortlist fix: 288 passed, 1 skipped;
`node --check static/app.js` passed. A new hosted Windows run is required for the
post-`a4f7b9d` fix. Even after that run, PR #18 is **not ready for final review or
merge** until the representative complete-posting extraction audit and the
candidate-specific 15-posting SWE shortlist audit are completed.

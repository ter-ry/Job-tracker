# Independent discovery quality audit — 2026-11-06

## Conclusion

**INCONCLUSIVE.** No live provider returned a posting, so the required independent source sample was unavailable. No quality-gate pass is claimed.

## Bounded attempts

- Canada remote and Toronto hybrid were each attempted once with LinkedIn and Indeed. Both scenarios returned zero rows; LinkedIn failed hostname resolution and Indeed failed resolving `apis.indeed.com`.
- The same two scenarios were each attempted once with Google Jobs and ZipRecruiter. Both returned zero rows; Google failed resolving `www.google.com` and ZipRecruiter failed resolving `api.ziprecruiter.com`.
- Read-only DNS probes in the environment resolved the public hostnames at probe time, indicating an intermittent or provider/network-path restriction rather than a malformed Job Tracker request. No further retry was made.

## Stored-link probe

The top 20 URLs in the isolated QA ranking were checked once: 15/20 returned HTTP 200 or redirect. Five pages were inspected for basic content signals. LinkedIn returned recognizable job-page titles for 3/3 sampled links, but only 1/3 had simple posting-content markers. Indeed returned HTTP 401 for both sampled links. These checks establish reachability only, not independent posting adjudication.

## Metrics

| Metric | Result |
|---|---:|
| Live jobs received | 0 |
| Independently verified originals | 0 |
| Top-20 precision | N/A |
| Required-years accuracy | N/A |
| Mandatory-skill accuracy | N/A |
| Eligibility errors | N/A |
| Seniority confusion | N/A |

The 104-job offline QA integrity report remains available under `.tmpqa`; it found 104 unique canonical postings and no duplicate canonical identities, but it is not independent source ground truth.

## Latest Windows source review

The final Windows capture contained 27 raw records and 21 unique canonical postings. A deterministic replay through the real application endpoint persisted all 21 unique jobs, removed 6 raw duplicates, and produced 9 actionable, 6 review-required, and 5 excluded rows. No persisted description was missing.

An independent review of the captured top 20 matched 18 rows to employer career/ATS pages or exact LinkedIn/Indeed pages. The two unresolved exact matches were Joblet-AI and Kablamo. This is supporting evidence only: the machine-readable audit contains no structured source annotations (`independently_verified_count=0`), so the required 40-posting sample and all accuracy/error metrics remain unavailable. The final quality-gate decision remains **INCONCLUSIVE**; no merge is authorized.

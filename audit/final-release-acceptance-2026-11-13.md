# PR #18 final release acceptance — 2026-11-13

Scope: draft PR #18. The audited application-fix commit is
`b4667057ca7ec1d72912d24a423ed2e87266cd7c` (parent
`a05a6002fd2a50a72bcbc3f474cdd25683b32cad`). This is an evidence record, not
approval to merge, tag, publish a release, or process real applicant data.

## CI and installer evidence

GitHub Actions [Windows release build #41](https://github.com/ter-ry/Job-tracker/actions/runs/43441763302)
passed for exactly that commit. Its validate, package, and historical jobs
passed; the publish job was skipped. The downloadable private-beta artifact is
`JobTracker-Windows-0.0.0-ci.41` (artifact 14046845707; SHA-256
`dff80274287250218fc4c1bf149e0532155b4f86a002d27fba1fc901dcda25a2`).

The package job passed Python tests, JavaScript validation, frozen executable
probe, package integrity, and the normal disposable-AppData installer lifecycle.
Those results make the artifact available for private-beta installation; they do
not authorize a public or stable release.

### Salary/benefit fix validation

The latest hosted validation is [Windows release build #43](https://github.com/ter-ry/Job-tracker/actions/runs/43454847715), which passed for the exact application-fix commit
`b4667057ca7ec1d72912d24a423ed2e87266cd7c`. Validate, package, and historical
jobs passed; publish was skipped. Its artifact is
`JobTracker-Windows-0.0.0-ci.43` (artifact 14052543477, SHA-256
`01a38aea775154df3d439523a7547124cf689fb3de8ff6ed57d27fc84bba73df`).

This run passed frozen executable launch, package integrity, normal disposable
installer lifecycle, checksum/upload, and the historical lifecycle gate. The
historical result remains narrowly scoped to schema 9-to-14 migration,
preservation, and safe refusal of ci.29 schema-13 rollback; it does **not**
claim a successful compatible rollback.

## Schema lifecycle: exact scope

The historical job successfully migrated the disposable database from ci.8
schema 9 to the current schema 14. It retained the saved job and `Applied`
status and created the pre-migration backup. It then considered ci.29, which
declares schema 13. Because schema 13 is incompatible with the current schema
14, the lifecycle script deliberately logged a compatible rollback skip and
did not start ci.29 against that database. It reinstalled the current build and
verified schema 14 and retained state.

Therefore **current-schema rollback was not tested**. The #41 historical job's
success is evidence that unsafe rollback was refused and that migration/re-upgrade
preserved state, not evidence of a successful ci.29 rollback. A matching-schema
historical binary is required before that acceptance claim may be made.

## Independent original-posting labels (recorded before extraction replay)

The following source facts were independently read from original employer or
Indeed pages on 2026-11-13. They are the reference labels for the subsequent
non-persistent extractor replay. “Absent” means the complete source did not
state an adjudicable value; it is not a claim that the employer offers none.

| Posting | Identity and original URL | Salary | Location / address | Benefits | Experience | Credentials | Required vs preferred technologies |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [PolicyMe — Junior Software Engineer (Remote)](https://jobs.lever.co/policyme/30e81807-adb5-44a9-baad-4beb75913694) | PolicyMe; exact canonical Lever URL | CAD $80,000–$110,000; cadence not stated in retrieved description | Remote; Canada eligibility; optional Toronto office, no street/postal stated | 20 vacation days; comprehensive employer-paid plan; L&D and AI-tooling budgets; stock options | no numeric minimum | absent | Required: Python, React, Redux, PostgreSQL, AWS, AI API/model project or hands-on experience, full-stack development. Preferred: none explicitly labelled. Core-stack-only n8n/LangChain/LangGraph are not requirements. |
| [Rose Rocket — Junior Software Engineer](https://jobs.ashbyhq.com/Rose%20Rocket/5ae4082e-4c3e-416f-a063-b00398e71542) | Rose Rocket; exact canonical Ashby URL | CAD $72,000–$88,000; cadence not stated in retrieved description | Hybrid; Toronto; downtown office, no street/postal stated | comprehensive benefits program/HCSA; parental top-up; stock options; equipment; 3 weeks vacation; winter holiday closure; 3 personal days | no numeric minimum | Bachelor’s in Computer/Software Engineering or related | Required: agentic coding tools, agile PM tools, Git/version control. Preferred: none explicitly labelled. NodeJS/NestJS/TypeScript, React/Websockets, PostgreSQL/Redis/DynamoDB/Elasticsearch, AWS/Docker/Kubernetes/GitHub Actions are exposure-only. |
| [McAfee — Full-Stack Developer](https://ca.indeed.com/viewjob?jk=d2b52a97a6ca1999) | McAfee; exact Indeed URL / `jk=d2b52a97a6ca1999` | CAD $100,772.50–$136,337.50; annual | source header Remote; Toronto, ON M5T 1X5 is eligibility geography, not commute destination | not independently adjudicated in this run | not independently adjudicated in this run | not independently adjudicated in this run; source’s Remote header conflicts with hybrid prose and must remain a visible conflict |
| [ExaSystems Dev Inc. — Full Stack Developer (ASP.NET / Blazor / MAUI)](https://ca.indeed.com/viewjob?jk=12ff082aaa676235) | ExaSystems Dev Inc.; exact Indeed URL / `jk=12ff082aaa676235` | From CAD $23/hour | Hybrid; Mississauga, ON L5L 5Y1. No street may be invented from city/postal-only location evidence. | not independently adjudicated in this run | not independently adjudicated in this run | not independently adjudicated in this run |

The four pages returned HTTP 200 with authentic full descriptions. This is a
four-posting, field-level sample, not a live discovery-provider accuracy rate.
No current JobSpy scrape was performed: the replay uses source text and
source-declared fields without writing a database or applicant data.

## Extraction replay results — before and after `b466705`

The independent labels above were fixed before this replay. The two ATS pages
were replayed through `normalize_jobspy_row` with their original JobPosting
descriptions and source-declared arrangement. The two Indeed facts were also
covered by the source-field regressions listed below; this was not a fresh
JobSpy provider request.

| Field | Before correctness / coverage | After correctness / coverage | Result / limitation |
| --- | ---: | ---: | --- |
| ATS identity and canonical URL | 4/4; 4/4 | 4/4; 4/4 | PolicyMe and Rose title/employer/URL values match exactly; the two Indeed identity/URL regressions also pass. This is pass-through integrity, not discovery accuracy. |
| ATS arrangement and geographic location | 2/2; 2/2 | 2/2; 2/2 | PolicyMe remains Remote/Canada eligibility; Rose remains Hybrid/Toronto. Neither gains a street or postal address. |
| Indeed arrangement/address examples | 2/2; 2/2 | 2/2; 2/2 | McAfee's explicit Remote classification wins over hybrid prose and exposes the conflict. Exa remains Hybrid with `L5L 5Y1`; no street is invented. |
| PolicyMe/Rose description salary endpoints | N/A; 0/2 | 2/2; 2/2 | The persistence-path fallback now retains CAD 80,000–110,000 and CAD 72,000–88,000 with source excerpts. Their retrieved descriptions do not state cadence, so it remains blank and no annual value is invented. |
| McAfee description-only salary fallback | 0/1; 0/1 | 1/1; 1/1 | CAD 100,772.50–136,337.50 per year retains both decimal endpoints and yearly cadence. |
| Exa description-only salary fallback | 0/1; 0/1 | 1/1; 1/1 | `From CAD $23/hour` retains only the lower endpoint; maximum, midpoint and annual equivalent remain unavailable because weekly hours are unstated. |
| Required technology / capability labels | 10/10; 10/10 | 10/10; 10/10 | PolicyMe: full-stack, Python, React, Redux, PostgreSQL, AWS, AI API/model experience. Rose: agentic tools, agile PM tools, Git. |
| Preferred versus exposure-only technologies | 6/6; 6/6 | 6/6; 6/6 | Rose's NodeJS/NestJS/TypeScript, React, PostgreSQL, AWS, Docker and Kubernetes remain outside required/preferred lists. |
| Credentials | 2/2; 2/2 | 2/2; 2/2 | PolicyMe correctly has no stated credential; Rose's Bachelor’s requirement is extracted with source evidence. |
| Numeric experience | 2/2; 2/2 | 2/2; 2/2 | Neither source states a numeric minimum and neither replay invents one. |
| Benefits | 11/12; 11/12 | 12/12; 12/12 | PolicyMe no longer promotes product-copy `Dental`; its five employee benefits retain excerpts. Rose now includes three weeks’ vacation and winter holiday closure, alongside its other five labelled benefits. |

Correctness and coverage are intentionally separate: missing source values are
not counted as correctness successes. The four-posting replay has no remaining
labelled salary or benefit false positives/omissions. It remains a four-posting
sample, not a population-level live-discovery accuracy claim; fixtures do not
close that wider gate.

## Source-access limitations

The current environment's proxy denied the three original ECE PDF hosts with
`CONNECT tunnel failed, response 403` on 2026-11-13:

- `wp.villacharities.com` (Villa Charities)
- `mothercraft.ca` (Mothercraft)
- `professionallearninghub.ca` (Cobblestone)

They are **unverified** for this acceptance pass. Existing fixtures and
historical snapshots remain regression evidence only and are not represented as
fresh live-source accuracy validation.

## Candidate-specific 15-posting SWE gate

The privately provided candidate résumé is not attached to this task and was
not read from the repository or a local user-data store. There are also no
fifteen complete authentic early-career SWE postings with independent
suitability labels in this task. To avoid circular scoring, predictions were
not examined and no candidate-specific metric was calculated:

| TP | FP | FN | TN | Precision | Recall |
| ---: | ---: | ---: | ---: | ---: | ---: |
| unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured |

This gate is **open**. Its owner-only inputs are a securely supplied résumé and
at least 15 complete authentic postings, each independently labelled before
Job Tracker predictions are viewed. Neither input may be committed to git.

## Functional regression evidence

At the application-fix commit, targeted ECE/SWE acceptance tests passed:
**11 passed, 282 deselected**. Salary/benefit/source focused tests passed:
**19 passed, 274 deselected**.
They cover ECE title-only search without résumé scoring, selected-profile
isolation and distinct applicant identity, Save/Applied persistence, source-ID
deduplication, McAfee remote-conflict handling, Exa postal-code preservation,
conservative remote directions, source-linked examples, and workplace
alternatives/distance handling. The entire Python suite passed: **308 passed,
1 skipped**. `node --check static/app.js` passed.

These tests establish the ECE functional behavior requested here: title-only
discovery retains the selected ECE profile without loading a résumé; profile
switching is isolated; Save and Applied ownership persists; provider IDs prevent
same-provider collisions; remote jobs suppress commute directions; and city-only
or unassigned workplaces stay conservative. They are software regressions, not
substitutions for the open live-source or candidate-accuracy gates.

PR #18 must remain draft and unmerged. Final acceptance remains open pending
the candidate-specific 15-posting evaluation and any required owner review.

# Independent SWE shortlist evaluation

Keep the candidate résumé and posting descriptions outside this repository.
Create a local `candidate.json` with the selected profile's `resume_text`,
`work_experience`, `projects`, `education`, and `key_skills` fields. Explicit
skill confirmations require the application's candidate profile database and
must be assessed separately; this standalone runner does not load them.

Collect at least 15 authentic, source-linked, junior or early-career postings
across frontend, backend, full-stack, Python, and adjacent software roles.
Include Java/Spring, .NET, React/TypeScript, Python/Flask, and cloud roles where
the real sample permits. Save a `postings.json` array outside the repository.
Each object needs `source_url`, `title`, the original `job_description`, and an
independently assigned `reviewed_label` (`strong`, `stretch`, `gaps`, or
`insufficient`). Reviewers should record separately which technologies are
required, preferred, and unverified, plus any professional-years expectation;
do not treat silence in the résumé as confirmed lack of experience.

Run `python scripts/evaluate_swe_shortlist.py candidate.json postings.json`
from a disposable working directory. The command prints per-posting required
evidence, predicted and reviewed labels, false positives and false negatives.
It does not save input or output. Inspect each disagreement against the original
posting and selected résumé before changing extraction rules. No accuracy
claim is possible until the real sample and selected résumé are supplied.

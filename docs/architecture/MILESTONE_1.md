# Milestone 1 foundation notes

Milestone 1 establishes the seams needed for the Career Pipeline rebuild while
keeping the existing Flask routes and generation algorithms compatible.

## Remaining bugs

- Resume and cover-letter generation can still produce unreliable wording or
  fail format-preserving DOCX edits for unusual templates. The existing
  grounding checks and generation status fields remain the source of truth.
- The legacy `app.py` still contains many route and domain helpers. New work
  should move one boundary at a time behind tests rather than perform a risky
  rewrite.
- The dashboard is intentionally empty when there are no saved jobs; it does
  not fabricate example roles.

## Milestone 1 verification (2026-10-15)

- Python environment: the project-local `.venv` on Python 3.12 was reused.
  Pinned requirements, including `python-docx==1.1.2` and
  `sentence-transformers==5.5.1`, import successfully. `pytest` is installed
  in the same environment for local validation.
- Automated validation: 85 tests passed; no tests failed or were skipped.
  Python compilation and `node --check static/app.js` also passed.
- Dashboard behavior: an isolated QA database rendered three real job records;
  the Career Pipeline header, statistics, category tabs, cards, scores,
  actions, navigation, and profile form were inspected in a browser. The AI
  category filter showed only the AI role. Profile data survived save,
  navigation, and reload. A separate empty database showed zero statistics
  and the intended empty-state message.
- Responsive contract: the rendered dashboard uses the documented compact
  dark shell and responsive CSS breakpoints at 640px, 760px, and 1180px.
- Screenshot capture: the browser-rendered dashboard was inspected during QA;
  no persistent screenshot artifact was added to the repository.
- No confirmed Milestone 1 application regression was found. Full visual
  comparison at additional viewport sizes remains a reviewer follow-up because
  the connected browser does not expose a viewport override in this session.

## Recommended next milestone

Milestone 2 should harden resume and cover-letter generation: move the current
algorithms behind the new service interfaces, add fixture-driven DOCX rendering
tests for representative templates, improve evidence conflict diagnostics, and
make failed generation recoverable without losing the prior document version.

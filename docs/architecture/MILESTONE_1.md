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

## Recommended next milestone

Milestone 2 should harden resume and cover-letter generation: move the current
algorithms behind the new service interfaces, add fixture-driven DOCX rendering
tests for representative templates, improve evidence conflict diagnostics, and
make failed generation recoverable without losing the prior document version.

# Milestone 2 document engine

## Scope

Document generation uses the existing grounded tailoring pipeline and DOCX
templates. Generation accepts an optional reusable candidate profile selection
(`candidate_profile_id`), plus `resume_id` and `cover_letter_template_id` when
the profile contains more than one document. Without a selection, the legacy
active profile remains the default.

## Safety guarantees

- Generated files are written with a unique generation token and never replace
  an uploaded template or an earlier successful output.
- A generator cannot report success unless its output path exists as a file.
- Failed retries remove only their incomplete new candidate and preserve the
  previous successful document path and download.
- Grounding validation remains a gate for résumé output; unsupported content is
  reported as a failure rather than being labelled generated.
- Cover-letter employer/location lines use comma punctuation rather than dash
  separators.

## Validation record

The milestone test suite covers readable DOCX output, structured templates,
multi-run paragraphs, bullets, tables, evidence validation, selected candidate
profiles, and failed-generation recovery. The complete suite currently passes
87 tests. Python compilation and Flask/python-docx imports pass. Ollama is
installed but its local service was unavailable in the restricted test session,
so model-dependent quality remains unverified and deterministic fallback tests
are the accepted validation path for this milestone.

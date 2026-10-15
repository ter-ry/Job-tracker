# Milestone 2 document engine

## Scope

Document generation uses the existing grounded tailoring pipeline and DOCX
templates. Generation accepts an optional reusable candidate profile selection
(`candidate_profile_id`), plus `resume_id` and `cover_letter_template_id` when
the profile contains more than one document. Without a selection, the legacy
active profile remains the default.

The Shortlist screen now exposes the complete desktop workflow: select a
candidate profile, choose its base résumé and cover-letter template, generate
or regenerate either document, inspect a text preview, review status/errors and
warnings, and download any successfully written DOCX. Download availability is
based on the preserved file path, so a failed retry does not hide the previous
successful document.

## Safety guarantees

- Generated files are written with a unique generation token and never replace
  an uploaded template or an earlier successful output.
- A generator cannot report success unless its output path exists as a file.
- Failed retries remove only their incomplete new candidate and preserve the
  previous successful document path and download.
- Grounding validation remains a gate for résumé output; unsupported content is
  reported as a failure rather than being labelled generated.
- Selected candidate profiles are isolated from the legacy profile and global
  approved-evidence records. A selected profile must provide a usable DOCX
  résumé template; missing evidence or invalid document IDs return an
  actionable error.
- Cover letters use the actual generation date and remove hyphens, en dashes,
  and em dashes by default. The preference is configurable on the Profile
  screen.

## Validation record

The milestone test suite covers readable DOCX output, structured templates,
multi-run paragraphs, bullets, tables, evidence validation, selected candidate
profile isolation, document-selection validation, preview responses, current
date and dash preferences, and failed-generation recovery. The complete suite
currently passes 90 tests. Python compilation and JavaScript syntax validation
pass. Playwright and a Node browser runner are not installed in this workspace;
the in-app browser also cannot reach the local Flask server, so a rendered
desktop E2E pass remains a local follow-up rather than a claimed automated
result. Ollama is installed but its local service was unavailable in the
restricted test session, so model-dependent quality remains unverified and
deterministic fallback tests are the accepted validation path for this
milestone.

## Local UI verification

From the repository directory, run `.venv\Scripts\python.exe app.py`, then open
`http://127.0.0.1:5000/` in Chrome or Edge. Use isolated QA data, open the
Shortlist tab, select a candidate profile, choose its résumé and cover-letter
template, generate, preview, download, and retry once with an invalid or
missing template to confirm that the previous successful download remains
available.

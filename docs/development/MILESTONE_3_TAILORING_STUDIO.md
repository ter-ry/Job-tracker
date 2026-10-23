# Milestone 3 Phase C: Interactive résumé tailoring studio

The first Phase C slice is profile and job scoped. It never edits the selected master résumé. A studio draft is created under the configured local data directory and is keyed by job, candidate profile, and selected résumé.

## Current workflow

1. Open Shortlist and locate an application preparation package with a selected candidate profile and résumé.
2. Select **Tailor résumé**.
3. Review the extracted job keyword inventory and original versus current résumé coverage.
4. Select an editable résumé bullet, revise it, and choose **Apply**. The change is written only to the copied draft DOCX.
5. Review the text preview and the layout result. Word COM measurements are used when available; otherwise the preview is explicitly approximate.
6. Approve the copied résumé for the matching application package. The approved DOCX is copied into that package and becomes its résumé download; the source résumé and other packages are unchanged.
7. Optionally request an Ollama suggestion. Suggestions are never applied automatically, and structured responses are accepted only when they contain a usable proposed_bullet.
8. Manage profile scoped confirmed experience and no experience records under Profile, or use the direct Yes, No and Skip actions beside a keyword.
9. Reuse a previously approved suggestion only after selecting a matching source bullet. A source fingerprint mismatch requires manual review.

The existing document generation and Keywords Score algorithms remain unchanged. The current slice supports editing or replacing an existing bullet, repeated edits, leaving it unchanged, and handing an approved copied DOCX into the matching preparation package. Add and move operations and a richer Word rendering pane remain follow-up work.

## Safety boundaries

- Drafts copy the selected DOCX and preserve the source file.
- Keyword coverage is recalculated from the actual draft text and excludes unapplied suggestions.
- AI suggestions are optional and rejected when they change quantified facts or fail basic safety checks.
- Keyword memory is scoped to the candidate profile and does not add unsupported résumé claims.
- No application submission or automatic package approval occurs.

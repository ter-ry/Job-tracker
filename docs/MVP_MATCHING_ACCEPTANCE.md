# Goal B — Matching Acceptance Matrix

This matrix records the executable Goal B regressions for SWE/ECE matching,
contextual qualification parsing, and default application ranking. Tests use
sanitized fixtures and the same classifier/ranking functions used by discovery
and persisted Inbox preparation; they do not reclassify the owner's database.

| Scenario | Evidence | Status |
| --- | --- | --- |
| A. Documented unrelated SWE occupations excluded | `tests/test_goal_b_matching.py::test_goal_b_documented_unrelated_swe_false_positives_are_excluded` | Complete |
| B–D. Broad technical recall, stretch roles, and adjacent administrators/consultants retained | `test_goal_b_adjacent_technical_roles_and_senior_stretch_remain_available` | Complete |
| E–I. Contextual seniority, internship wording, ages/history, required/preferred ranges and malformed dashes | `test_goal_b_description_junior_reference_does_not_override_unlevelled_title`; `test_goal_b_experience_context_preserves_required_preferred_and_ages` | Complete |
| J. Unknown seniority is neutral, not senior | `test_goal_b_default_ranking_keeps_unknown_neutral_and_ece_supply_last` | Complete |
| K–P. ECE title/context, full-time precedence, supply fallback, mixed/ECA/teacher handling | `test_goal_b_ece_contextual_employment_and_mixed_titles` | Complete |
| Q. ECE does not require résumé qualification defaults | Existing `tests/test_final_acceptance_corrections.py` ECE policy tests plus Goal B classifier fixtures | Complete |
| R–T. Fresh/persisted/reassessment paths and canonical decision protection | Existing discovery/reassessment and canonical acceptance suites; no owner DB replay | Complete in regression fixtures |
| U. 10,000-record Inbox performance | `tests/test_mvp_performance.py` | Complete |

The independent 100-posting owner-cohort evaluation remains an owner-only gate
until the private labelled export is supplied. Synthetic fixtures above are not
represented as live recall or precision measurements.

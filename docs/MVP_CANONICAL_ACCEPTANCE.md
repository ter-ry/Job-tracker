# Canonical Vacancy Reconciliation Acceptance

This table records executable sanitized integration evidence for the vacancy
identity workstream. It does not claim replay of the owner's private audit
export or owner database.

| Scenario | Implementation location | Executed regression | Actual result | Remaining limitation |
|---|---|---|---|---|
| A | `find_canonical_identity_match`, `persist_discovery_jobs` | `test_A_B_N_future_acquisition_is_one_opportunity_and_preserves_skip` | Passed: equivalent Indeed/Glassdoor acquisition attaches to one job | Owner source corpus not replayed |
| B | Applicant state overlay and canonical persistence | Same A/B test | Passed: skipped state remains skipped and is not actionable | None in sanitized fixture |
| C | Reconciliation decision transfer and Inbox counts | `test_C_D_E_P_decisions_transfer_independently_and_applied_never_ready` | Passed: applied Glassdoor decision transfers to canonical and Ready to Apply is zero | Owner application history not replayed |
| D | Same transfer path with canonical/source order independent | Same C/D/E/P test | Passed for reverse source ordering in the integration fixture | Larger historical import corpus not replayed |
| E | Applicant-scoped `discovery_applicant_states` transfer | Same C/D/E/P test | Passed: decisions remain independent by applicant | None in sanitized fixture |
| F | Preview `decision_conflicts` and explicit resolution gate | `test_F_K_conflicts_and_stale_confirmation_are_explicit` | Passed: conflicting decisions reject apply before mutation | UI conflict-resolution editor is not part of this backend milestone |
| G | Union-find canonical grouping and source aliases | `test_G_J_three_sources_aliases_form_one_group_without_cycles` | Passed: three sources produce one canonical group and two linked rows | None in sanitized fixture |
| H | Requisition token conflict in `vacancy_identity_pair` | `test_H_I_distinct_requisitions_and_workplaces_remain_separate` | Passed: distinct requisitions remain separate | Provider-specific requisition parsing may need future source adapters |
| I | Workplace conflict guard in `vacancy_identity_pair` | Same H/I test | Passed: materially different location remains separate | Address evidence quality remains provider-dependent |
| J | `normalize_dedupe_company` employer aliases | `test_G_J_three_sources_aliases_form_one_group_without_cycles` | Passed: Inc/Corporation/trading-name variants group with supporting evidence | Alias map is intentionally conservative and finite |
| K | `reconciliation_state_fingerprint` checked at apply | `test_F_K_conflicts_and_stale_confirmation_are_explicit` | Passed: changed applicant decision rejects stale preview | Fingerprint is process-local database state, not a distributed lock |
| L | Transactional rollback with conditional state restoration | `test_M_L_rollback_restores_relationship_and_decisions_without_losing_later_change` | Passed: relationship restores while later Applied decision is retained | Newly presented canonical history is retained rather than risking overwrite |
| M | Applied reconciliation status and idempotent endpoint | `test_O_uncertain_candidates_are_review_only_and_M_is_idempotent` | Passed: repeated apply returns idempotent success | None in sanitized fixture |
| N | Future acquisition canonical attachment | `test_A_B_N_future_acquisition_is_one_opportunity_and_preserves_skip` | Passed: later provider posting updates aliases/source links without a new job | Requires strong evidence; uncertain rows go to review |
| O | `requires_review` candidate status and explicit merge resolution | `test_O_uncertain_candidates_are_review_only_and_M_is_idempotent` | Passed: uncertain candidate cannot auto-merge | Review UI workflow remains a follow-up |
| P | Canonical filtering in Inbox/counts and applicant state transfer | `test_C_D_E_P_decisions_transfer_independently_and_applied_never_ready` | Passed: applied count remains visible and canonical is not Fast Apply eligible | Full UI counter replay is covered by existing browser suite, not owner data |
| Q | Blocked company/title/location candidate generation | `test_Q_candidate_generation_is_bounded_for_10000_mixed_records` | Passed: 10,000 mixed records completed under 3 seconds with zero comparisons/candidates | Benchmark is sanitized and hardware-dependent |

## Safety guarantees

- Preview writes only a reconciliation proposal and conflict ledger.
- Apply requires the exact preview token, unchanged state fingerprint, explicit
  confirmation, and explicit resolutions for uncertain/conflicting groups.
- Source rows, provider IDs, URLs, descriptions, aliases, and memberships are
  retained; duplicate rows are linked to the canonical row rather than deleted.
- Applied decisions are never replaced by a weaker decision.
- Rollback conditionally restores only relationships and decisions that have not
  changed since apply, preserving later applicant actions.

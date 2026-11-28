# PR #18 factual extraction recheck

This pass rechecked the 20 source-linked salary excerpts already recorded in
`occupation-factual-acceptance-20261109.json` (10 ECE, 10 software). These are
not complete original descriptions or 20 newly retrieved live postings. The
cloud proxy denied access to an employer ATS page, so title, employer, original
application URL, benefits, credentials, complete experience clauses, and
workplace address cannot be independently scored from these excerpts.

All 20 original advertised salary endpoint pairs and pay units were preserved
by `parse_salary_text` when inspected against the recorded excerpts. Exact
annualized integers matched the stored labels in 19/20 cases. For `ece-03`
(Mothercraft), the source excerpt is `$24.47-$28.36 per hour`: multiplying by
2,080 yields $50,897.60-$58,988.80. The parser rounds to $50,898-$58,989,
while the stored labels are $50,897-$58,988. The one-dollar discrepancy is a
reference rounding convention issue, not evidence that the advertised hourly
range was extracted incorrectly. No independent 20-posting full-description
accuracy percentage is claimed.

Confirmed defects corrected in this pass:

- `$60,000-$63/year` was accepted as a $60,000-to-$63 annual range. It is now
  unavailable rather than silently completed with guessed digits.
- An unlabeled street address anywhere in a provider description could become
  the workplace, including a corporate mailing address. Unlabeled addresses
  now need explicit job/workplace context. The previously captured Maple RECE
  address at 9350 Keele St remains extractable.

The Windows workflows for PR #18 remain queued with zero jobs at the time of
this recheck. No hosted packaging or installer lifecycle result is claimed.

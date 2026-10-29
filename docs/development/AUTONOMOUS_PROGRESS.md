# Integrated workflow progress

This branch combines the existing Discovery, Application workspace, preparation,
Tailoring Studio, document preview, and approval flows for final QA.

Current work:

- Word résumé preview now fingerprints layout inputs, reuses measurements, and
  validates plus exports the current DOCX in one Word session when a fresh
  render is needed.
- The existing Shortlist queue is presented as the Application workspace so
  preparation, tailoring, review, approval, downloads, and the manual apply
  handoff remain one persistent workflow.

Remaining validation is recorded in the final task report: full regression,
browser workflow, Word timing, and isolated QA server identity.

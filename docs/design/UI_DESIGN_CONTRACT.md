# Career Pipeline UI design contract

`career-pipeline-reference.png` is the permanent visual reference for the
Career Pipeline dashboard. It defines the dark, compact, evidence-first visual
language: near-black canvas, thin neutral borders, bright readable type,
large summary metrics, category tabs, and full-width job cards with a right
aligned fit score and action state.

Implementation requirements:

- Dashboard content must come from API data; placeholder or fictional jobs are
  not permitted in the rendered application.
- Preserve accessible focus states, semantic headings, and responsive layout.
- Keep the dashboard shell independent from discovery, tracker, profile, and
  document-generation algorithms.
- Changes to typography, spacing, color, card structure, or interaction model
  should be compared against the reference image before merging.

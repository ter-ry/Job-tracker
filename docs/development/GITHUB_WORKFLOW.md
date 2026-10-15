# Job Tracker GitHub development workflow

The persistent project policy is installed in the root [`AGENTS.md`](../../AGENTS.md). Future Codex sessions should follow that policy automatically.

## Verified baseline

- Repository: `ter-ry/Job-tracker`
- Default branch: `master`
- Development branch: `codex/foundation-architecture-rebuild`
- Verified development HEAD: `c1b47d7358e74cae96bbce2b1344d897e20605eb`
- Verified parent: `6a5d2987f14b76c39ae0cae196a0dc01dd11ad52`

The development branch exists on GitHub and is two commits ahead of `master` (`8a4c2e929df00e84b51ca790a4f12bc2b2ef28a9`). The local checkout was clean and had the same branch and commit at the time this guide was written.

## Flowtally evidence

The connected GitHub repository is `ter-ry/restaurant-helper`. PRs 112, 113, and 114 verify a remote branch/PR pattern:

- PR 112 used `codex/showcase-preparation-final`, contained 3 commits and 10 changed files, and was merged into `main`.
- PR 113 used `codex/showcase-inventory-complete`, contained 1 commit and 3 changed files, and used PR 112's merge commit as its base.
- PR 114 used `codex/recording-readiness-audit`, contained 3 commits and 10 changed files, and used PR 113's merge commit as its base.

This verifies that Flowtally handled multi-commit PR revisions and complete remote file batches through ordinary GitHub branches and pull requests. The changed-file lists were complete for those PRs, but all inspected files were text; these PRs do not demonstrate binary transfer or deletion handling.

The GitHub evidence does not reveal how local Windows edits were transferred into those commits, how local `HEAD` was reconciled afterward, or how already-committed local changes were marked as processed. No local Flowtally checkout or synchronization log was available in the connected evidence. Those points remain unverified rather than inferred.

## What is verified

The GitHub connector can perform this remote-only sequence without local Git metadata writes:

1. Create a branch from a remote branch or commit.
2. Create UTF-8 text files and commit them on that branch.
3. Inspect the resulting commit, branch head, ancestry, and changed-file list.
4. Create and update a draft pull request.
5. Close a pull request without merging.

The controlled test used branch `codex/job-tracker-integration-test`, commit `2526aac2bbeac0b1328a64d9d0f5e5eb98f95013`, and exactly one harmless documentation file. It did not touch the local checkout or `master`.

## Routine session procedure

1. Edit source files in the local checkout.
2. Run Flask/Python tests and any local Ollama checks that are relevant.
3. Inspect the local diff and test results.
4. For remote publication, build a GitHub commit from the intended remote base using connector Git-data operations (blobs, tree, commit, then branch ref update), or use the connector's file operation for a single UTF-8 file.
5. Verify the remote branch head and compare it with its target branch before opening or updating a PR.
6. Create or update the PR and verify its changed-file list.

Do not describe a remote connector commit as proof that the local checkout has been synchronized. After a remote-only commit, the local checkout is known to be stale until a supported reconciliation operation is demonstrated.

## Unsupported or not demonstrated

- The connector test did not demonstrate transferring an arbitrary local working tree as a complete batch.
- Binary-asset transfer, deleted-file handling, and multi-commit replay were not demonstrated in this session.
- Flowtally's remote PR mechanics are verified above, but its local-to-remote transfer and local-HEAD reconciliation mechanics remain unverified.
- The connector does not expose a branch-delete operation. The temporary test PR is closed, but the temporary branch remains until it is deleted manually on GitHub.
- Native Windows restricted workspace-write prevents routine local Git metadata updates in this checkout. Therefore local edits, local tests, remote connector commits, and PR creation are individually supported, but a complete automatic local-edit-to-local-HEAD-to-remote reconciliation loop is not verified.

Codex Desktop's managed-worktree capability is a supported way to create or attach an isolated Git worktree, but it is not a demonstrated reconciliation mechanism for this existing Windows checkout. It should not be treated as proof that connector-created commits advance this checkout's local `HEAD`.

## Temporary test cleanup

Delete the closed remote branch `codex/job-tracker-integration-test` from the GitHub branch page. This is the only remaining cleanup from the controlled connector test; do not merge PR #1.

# Job Tracker development policy

## Local development

- Use `C:\Users\ter23\Documents\Job tracker` for source edits, Flask/Python tests, JavaScript validation, and optional local Ollama testing.
- Remain in the restricted `workspace-write` environment. Never switch to danger-full-access, alter Windows ACLs, use WSL, or bypass sandbox controls for Git work.
- At the beginning of every development task, inspect local status, the current branch, the remote branch head, and branch divergence. Identify unrelated changes before editing and preserve them.

## GitHub publication

- The connected GitHub repository is `ter-ry/Job-tracker`; the default branch is `master`.
- When an approved implementation task is complete and its relevant tests pass, stage only the intended files, inspect the staged diff, commit locally, and push the corresponding feature branch without waiting for a separate “commit and push” instruction.
- Use `sandbox_permissions: require_escalated` only for individual Git commands that need protected `.git` metadata access. Keep the session in workspace-write; do not switch to danger-full-access or create broad reusable approval rules without explicit permission.
- Create or update a draft pull request targeting `master` when appropriate. Never merge or deploy automatically.
- Remote commits must contain the actual validated batch, including new, modified, deleted, and binary files. Use blob/tree operations and safe encodings when the file operation does not cover the required file type.
- Before reporting completion, verify the remote commit SHA, parent/base, changed-file diff, branch head, and pull-request contents.

## Synchronization and safety

- After pushing, verify that local `HEAD` and the remote feature-branch `HEAD` match. Use the GitHub connector primarily for PR creation, PR updates, reviews, and verification, and as a fallback for remote Git operations when appropriate.
- Do not overwrite unrelated local changes, force-push, rewrite history, commit credentials or secrets, alter production data, modify Flowtally, or bypass the sandbox.
- Do not begin a new milestone without explicit user approval in the current conversation.

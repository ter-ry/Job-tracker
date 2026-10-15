# Job Tracker development policy

## Local development

- Use `C:\Users\ter23\Documents\Job tracker` for source edits, Flask/Python tests, JavaScript validation, and optional local Ollama testing.
- Remain in the restricted `workspace-write` environment. Never switch to danger-full-access, alter Windows ACLs, use WSL, or bypass sandbox controls for Git work.
- At the beginning of every development task, inspect local status, the current branch, the remote branch head, and branch divergence. Identify unrelated changes before editing and preserve them.

## GitHub publication

- The connected GitHub repository is `ter-ry/Job-tracker`; the default branch is `master`.
- Prefer the connected GitHub API tools for branch creation, Git objects, commits, branch reference updates, and pull requests. Do not repeatedly attempt `git add`, `git commit`, or `git push` when the Windows sandbox denies `.git` writes.
- When an approved implementation task is complete and its relevant tests pass, publish the validated source changes to the appropriate remote feature branch without waiting for a separate “commit and push” instruction.
- Create or update a draft pull request targeting `master` when appropriate. Never merge or deploy automatically.
- Remote commits must contain the actual validated batch, including new, modified, deleted, and binary files. Use blob/tree operations and safe encodings when the file operation does not cover the required file type.
- Before reporting completion, verify the remote commit SHA, parent/base, changed-file diff, branch head, and pull-request contents.

## Synchronization and safety

- A GitHub connector commit does not advance the local Windows Git `HEAD`. Verify local and remote synchronization before starting subsequent work; never assume it.
- Do not overwrite unrelated local changes, force-push, rewrite history, commit credentials or secrets, alter production data, modify Flowtally, begin Milestone 2, or bypass the sandbox.
- Codex Desktop managed worktrees may provide isolated Git-backed checkouts, but no supported operation has been demonstrated that reconciles this existing Windows checkout's local `HEAD` with connector-created remote commits under restricted workspace-write. Do not claim full end-to-end automation until that reconciliation is demonstrated.
- If local reconciliation remains unavailable, continue with local validation plus connector publication and clearly report the remaining synchronization action or limitation. Do not invent a custom synchronization script.

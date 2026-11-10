# Windows release pipeline

This document describes the future Windows distribution path. It does not publish a release and does not make the current application stable.

## Design

- `.github/workflows/windows-release.yml` runs source tests, JavaScript validation, an isolated Flask launch smoke test, a PyInstaller build, package checks, Inno Setup, and SHA-256 generation.
- `pull_request` runs the same validation and packaging path for packaging-related changes, using a non-release version such as `0.0.0-ci.123`; it uploads an internal installer artifact but has no release-publishing path.
- `workflow_dispatch` creates a validation artifact only. It never publishes a GitHub Release.
- A stable release requires an explicitly pushed semantic-version tag such as `v1.0.0`. The `release` environment must require an approved reviewer before the publishing job can run.
- The published installer is named `JobTracker-Setup-v1.0.0.exe`, with a matching `.sha256` file.
- PRs and merges to `master` do not publish releases.

The installer contains a PyInstaller onedir application and creates Start-menu and desktop shortcuts. `release_packaging/windows/launcher.py` starts Waitress on `127.0.0.1:5000`, waits for `/api/health`, and opens the default browser. `scripts/frozen_windows_smoke_test.py` launches the actual frozen executable against disposable data and checks health, version, templates, static assets, SQLite creation, and clean shutdown. A named Windows mutex (`JobTrackerInstance`) prevents a second application instance and matches Inno Setup's `AppMutex`; a file lock is used only on non-Windows test platforms. If an existing healthy instance is found, a second launch only opens the browser.

## User data and upgrades

The launcher sets `JOB_TRACKER_DATA_DIR` to `%APPDATA%\Job Tracker` before importing Flask. The following remain outside the installation directory and are preserved across upgrades and uninstall/reinstall:

- `jobs.sqlite` and SQLite journal/WAL files
- candidate profiles, resumes, cover-letter templates, uploads, and application history
- saved searches, discovery caches, generated documents, semantic caches, and settings
- `backups\jobs-before-migration-*.sqlite`

Before a schema upgrade, the guarded database initializer creates a consistent SQLite backup using SQLite's backup API. If that backup cannot be created, the migration aborts before schema writes. Migrations are additive and versioned in `db/migrations.py`; they must not delete or rewrite user records. The release smoke test asserts that an isolated data root is used.

## Dependency and size implications

The package keeps the current runtime dependencies, including JobSpy, pandas, python-docx, Flask, Waitress, sentence-transformers, and PyTorch-related modules. The PyInstaller spec explicitly collects the sentence-transformers package and torch submodules instead of silently disabling semantic matching. These packages can make the onedir bundle and installer substantially larger than the source application; the CI artifact size is part of the package check and must be recorded during the first real build.

The `all-MiniLM-L6-v2` model weights are not silently replaced by keyword matching. The current application already falls back to keyword matching if the model is unavailable. A release decision must choose one of these explicit policies before v1.0.0:

1. bundle the model cache, accepting a much larger installer; or
2. download the model on first semantic-search use into the user's cache, with visible progress and a documented offline fallback.

Ollama remains an optional local integration. The installer does not bundle or start Ollama, does not download a model, and does not remove its existing settings or APIs. The UI continues to report when Ollama is unavailable.

## Future updater safety

The current `Check for updates` control is read-only: it queries the latest GitHub Release, normalizes `v1.0.0` and `1.0.0` to the same semantic version, and opens the release page only when a strictly newer release exists. It does not download, replace, or install anything.

A future updater must:

1. ask for confirmation;
2. download to a staging directory under `%LOCALAPPDATA%\Job Tracker\updates`;
3. verify the SHA-256 checksum and, after signing is adopted, the Authenticode signature;
4. create/verify a current data backup;
5. close the running app before the installer replaces files;
6. launch the installer as a separate process and never overwrite a running executable; and
7. leave the user data directory untouched if download, verification, or installation fails.

No silent updates or automatic database resets are permitted.

## Developer release procedure

1. Finish and merge application work through normal PR review. Confirm the release branch is based on the latest `master` and that discovery, ECE search, extraction, Pipeline, concurrency, and tailoring tests pass.
2. Run the workflow manually with a test version such as `0.0.0-rc.1`. Manual runs build validation artifacts only and cannot publish a release. Download the artifact, verify the checksum, install it on a disposable Windows account or VM, and confirm it starts on localhost, opens a browser, and creates data under `%APPDATA%\Job Tracker`.
3. Seed disposable data, install a newer test build, and verify jobs, profiles, saved searches, documents, and application history remain intact. Test a migration from a copy of the prior SQLite database and verify the pre-migration backup.
4. Confirm the packaged feature set, including semantic fallback, document generation, optional Ollama settings, discovery providers, export, and external job links.
5. Configure the GitHub `release` environment with required reviewers; the workflow environment only becomes an approval gate after those reviewers are explicitly configured in repository settings. Confirm signing credentials are available. Unsigned builds are suitable for private testing but are not first-public-release ready.
6. Create and push an approved stable tag: `git tag -a v1.0.0 -m "Job Tracker v1.0.0"` then `git push origin v1.0.0`. Only `vMAJOR.MINOR.PATCH` tags can reach the publish job; prerelease tags such as `v1.0.0-rc.1` are validation-only. The workflow must pass before the release reviewer approves publication.
7. Verify the GitHub Release asset filename and checksum, then test download/install from the release page on a clean Windows machine.

## Rollback

Rollback means selecting a prior application installer or commit; it does not mean deleting or replacing the data directory. Stop Job Tracker, back up `%APPDATA%\Job Tracker`, install the known-good application version, and let only backward-compatible migrations run. If a migration is incompatible, restore a copy of the pre-migration SQLite backup to a separate recovery directory and investigate; never overwrite the only user database automatically.

## SmartScreen and signing

Unsigned installers and executables will normally produce Windows SmartScreen warnings, especially for a new publisher or low-download release. Code signing is not free: obtain an Authenticode certificate from a trusted certificate authority, protect the signing key, sign both the executable and installer, and publish the signing policy and timestamping configuration. SmartScreen reputation is gradual and cannot be guaranteed by the workflow. The first public release must not claim a warning-free install until signed artifacts are tested on a clean Windows machine.

## First-public-release readiness checklist

- [ ] Application behavior and frozen acceptance criteria are stable on `master`.
- [ ] A Windows runner has produced a successful installer and checksum.
- [ ] The PyInstaller bundle has been size-reviewed; the semantic model policy is chosen and tested.
- [ ] Clean-install, upgrade, reinstall, rollback, and migration tests pass with disposable user data.
- [ ] `%APPDATA%\Job Tracker` preservation has been verified on multiple Windows accounts/computers.
- [ ] Localhost binding and single-instance behavior have been verified.
- [ ] Ollama optional behavior and all current features have been tested in the packaged build.
- [ ] Code signing certificate, key protection, timestamping, and SmartScreen expectations are documented.
- [ ] GitHub `release` environment approval is configured.
- [ ] Release notes, checksum verification, support/rollback instructions, and privacy/data-location notices are ready.
- [ ] An explicitly approved semantic-version tag is the only input to the first public release.

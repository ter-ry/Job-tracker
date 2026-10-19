# Milestone 3 Phase A: Automated discovery

Phase A adds named, persistent searches around the existing JobSpy discovery pipeline. It reuses the current source adapters, date filtering, salary normalization, geocoding, Canadian location handling, deduplication and Job Priority scoring.

## Saved searches

Saved searches are available from the Discovery tab. Each search stores its own keywords, location, remote preference, seniority note, minimum salary, source list, posting recency and interval. New searches are disabled by default. **Run now** performs one isolated discovery run; it does not shortlist results automatically.

The Discovery inbox keeps new results as `Saved` jobs and records first seen, last seen and encounter count. Repeated results update only discovery metadata and do not overwrite statuses, notes, generated documents or other user-edited fields. Review, shortlist, ignore and original-link actions remain explicit.

## Background worker

The worker is independent of Flask and can run while the browser is closed. From the repository root:

```powershell
.venv\Scripts\python.exe scripts\discovery_worker.py --once
```

Enable the database scheduler in the Discovery tab, then install the optional per-user Windows task once from PowerShell. The installer uses PowerShell ScheduledTasks cmdlets and is safe for repository and data paths containing spaces:

```powershell
.\scripts\install_discovery_task.ps1 -IntervalMinutes 15 -DataDir "C:\Users\ter23\Documents\Job tracker\data"
```

Remove it later with:

```powershell
.\scripts\uninstall_discovery_task.ps1
```

For isolated QA, use a separate task name and data directory. The installer is idempotent for that task name and does not alter another task:

```powershell
.\scripts\install_discovery_task.ps1 -TaskName "Job Tracker Discovery QA" -DataDir "C:\path\to\qa data"
.\scripts\uninstall_discovery_task.ps1 -TaskName "Job Tracker Discovery QA"
```

The worker checks each enabled search's next-run time, records per-source outcomes and run history, and uses SQLite leases to prevent duplicate workers or overlapping runs. Scheduler execution is disabled by default.

For a long-running local worker:

```powershell
.venv\Scripts\python.exe scripts\discovery_worker.py --daemon --poll-seconds 60
```

The worker uses `JOB_TRACKER_DATA_DIR` when set, so QA runs can use an isolated database without touching the normal application data.

## Phase B: application preparation

Phase B adds a persistent review queue without changing the existing job status, Job Priority calculation, Keywords Score, or document engines. Discovery results can be queued manually from the inbox, or a saved search can opt into automatic preparation with a minimum Job Priority, a selected candidate profile, and confirmed Canadian eligibility. Explicitly restricted postings are excluded and unknown eligibility remains a manual review condition.

The queue progresses through `queued`, `preparing`, `ready_for_review`, `approved`, `skipped`, and `failed`. Preparation runs the existing résumé and cover letter generation engines with the selected profile and stores actual errors. It never submits an application and never changes a job to Applied. The standalone worker processes eligible queued packages after discovery and can resume expired work through SQLite leases:

```powershell
.venv\Scripts\python.exe scripts\discovery_worker.py --once
```

The Shortlist tab contains the application preparation review queue. Users can inspect the generated documents, Keywords Score, errors and original application link, then approve or skip a package. Approval means the package is ready for the user's next manual application step; it is not a submission.

## API surface

- `GET/POST /api/discovery/searches`
- `PUT/DELETE /api/discovery/searches/<id>`
- `POST /api/discovery/searches/<id>/run`
- `GET /api/discovery/inbox`
- `POST /api/discovery/inbox/<id>/review`
- `POST /api/discovery/inbox/<id>/ignore`
- `GET /api/discovery/runs`
- `GET/PUT /api/discovery/scheduler`
- `GET/POST /api/preparation/queue`
- `POST /api/preparation/<id>/prepare`
- `POST /api/preparation/<id>/regenerate`
- `POST /api/preparation/<id>/review`
- `GET /api/preparation/<id>/preview`

Eligibility is deliberately conservative: Canadian eligible, explicitly restricted, and unknown are distinct states. Unknown eligibility is never treated as confirmed Canadian eligibility. Discovery errors are retained per source so a failed provider does not discard successful results from other providers.

Form filling, browser submission, CAPTCHA handling and automatic application submission remain out of scope for Phase B and are not implemented.

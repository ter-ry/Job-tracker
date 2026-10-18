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

Enable the scheduler in the Discovery tab, then run the command from Windows Task Scheduler at a reasonable interval (for example every 15 minutes). The worker checks each enabled search's next-run time, records per-source outcomes and run history, and uses a SQLite lease to prevent duplicate workers or overlapping runs. Scheduler execution is disabled by default.

For a long-running local worker:

```powershell
.venv\Scripts\python.exe scripts\discovery_worker.py --daemon --poll-seconds 60
```

The worker uses `JOB_TRACKER_DATA_DIR` when set, so QA runs can use an isolated database without touching the normal application data.

## API surface

- `GET/POST /api/discovery/searches`
- `PUT/DELETE /api/discovery/searches/<id>`
- `POST /api/discovery/searches/<id>/run`
- `GET /api/discovery/inbox`
- `POST /api/discovery/inbox/<id>/review`
- `POST /api/discovery/inbox/<id>/ignore`
- `GET /api/discovery/runs`
- `GET/PUT /api/discovery/scheduler`

Eligibility is deliberately conservative: Canadian eligible, explicitly restricted, and unknown are distinct states. Unknown eligibility is never treated as confirmed Canadian eligibility. Discovery errors are retained per source so a failed provider does not discard successful results from other providers.

Phase B is intentionally out of scope: form filling, browser submission, CAPTCHA handling and automatic application submission are not implemented.

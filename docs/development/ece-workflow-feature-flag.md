# ECE workflow feature flag

Job Tracker runs in SWE-only mode by default. Existing ECE profiles, source
records, preferences, documents, decisions and audit history remain in the
database, but ECE controls and scheduled/discovery execution are suspended.

To temporarily restore the complete multi-applicant workflow, set the
environment variable before starting Flask and the discovery worker, then
restart both processes:

```powershell
$env:JOB_TRACKER_ECE_ENABLED = "1"
python app.py
```

Unset the variable, or set it to `0`, and restart to return to SWE-only mode.
The flag is intentionally configuration-based and reversible; it does not
delete or migrate any ECE data.

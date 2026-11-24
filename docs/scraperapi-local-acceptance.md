# Local ScraperAPI and Job Tracker acceptance

These commands use the repository virtual environment and do not touch the
production data directory. Run them from the repository root in PowerShell.

## Synchronize and validate the checkout

```powershell
git fetch origin
git switch codex/jt-primary-search-p0
git pull --ff-only origin codex/jt-primary-search-p0
$expected = "PASTE_THE_EXACT_SHA_FROM_THE_OWNER_HANDOFF"
if ((git rev-parse HEAD) -ne $expected) { throw "Unexpected Job Tracker commit" }
```

Only update dependencies when the checkout changed its requirements:

```powershell
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe -m pip check
```

Local checks that do not make provider requests:

```powershell
$env:SCRAPERAPI_ENABLED = "0"
& .\.venv\Scripts\python.exe -c "from sources.scraperapi_source import ScraperApiConfig; c=ScraperApiConfig.from_environment(); print({'enabled':c.enabled,'allowed_hosts':c.allowed_hosts,'timeout_seconds':c.timeout_seconds,'max_cost':c.max_cost,'api_key_configured':bool(c.api_key)})"
& .\.venv\Scripts\python.exe -m pytest -q tests/test_scraperapi_workplace.py tests/test_scraperapi_cost_preflight.py
& .\.venv\Scripts\python.exe -m pytest -q
node --check static/app.js
```

## Cost preflight (explicit owner action)

This calls only ScraperAPI’s `account/urlcost` endpoint. It does not retrieve
either target posting. Whether the account endpoint itself consumes credits is
reported as unknown and should be confirmed against the owner’s current plan
before running it.

```powershell
$env:SCRAPERAPI_API_KEY = "YOUR_KEY"
$env:SCRAPERAPI_ENABLED = "1"
$env:SCRAPERAPI_ALLOWED_HOSTS = "ca.indeed.com"
$env:SCRAPERAPI_MAX_COST = "1"
& .\.venv\Scripts\python.exe scripts\scraperapi_cost_preflight.py `
  --max-credits 2 `
  --output scraperapi-cost-preflight.json
```

Do not run the retrieval benchmark unless the owner explicitly approves it:

```powershell
& .\.venv\Scripts\python.exe scripts\benchmark_scraperapi_workplace.py `
  --max-credits 2 `
  --output scraperapi-benchmark.json
```

The benchmark permits at most two target requests, sends the lower of the
configured per-request cap and remaining budget, stops when actual cost is
unknown, and reports `identity_status`, `failure_classification`,
`provider_error_message`, `response_headers`, `recommended_action`, and
`credits_consumed_status`. It does not retry forbidden responses.

## Isolated local QA on port 5001

The Windows launcher, rather than `app.py`, owns the QA port and instance
identity. The test-mode override is required for a disposable `%TEMP%` root.

```powershell
$qaRoot = Join-Path $env:TEMP "JobTracker-LocalQA"
$env:JOB_TRACKER_TEST_MODE = "1"
$env:JOB_TRACKER_DATA_DIR = $qaRoot
& .\.venv\Scripts\python.exe release_packaging\windows\launcher.py --qa
```

In another PowerShell window:

```powershell
Invoke-RestMethod http://127.0.0.1:5001/api/health
Invoke-RestMethod http://127.0.0.1:5001/api/qa/status
Start-Process http://127.0.0.1:5001/
```

The health response must show the QA database under `$qaRoot`; the QA status
must report `active: true`, `mode: "qa"`, and port `5001`. Stop the foreground
launcher with `Ctrl+C`, then rerun the same command to verify restart
persistence. For a separate fresh disposable session use a different root and
`--fresh-qa`, which binds port `5002`.

## Owner acceptance checklist

- SWE and ECE searches use the intended applicant profile.
- Indeed, Glassdoor and Employer Direct outcomes identify working, failed and
  incomplete providers separately.
- Workplace candidates show source evidence and remain unconfirmed until the
  owner verifies them.
- Cross-source duplicates, Seen, Saved, Applied and Skipped states persist
  after refresh and restart.
- Continue Search reports cumulative and current-batch counts truthfully.
- Search diagnostics distinguish blocked providers from empty results.
- The QA database path and `/api/qa/status` remain isolated from production.
- ScraperAPI remains opt-in and experimental; a 403 is recorded with its
  evidence-backed classification and is not automatically retried.

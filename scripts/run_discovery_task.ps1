param(
    [string]$DataDir = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) { throw "Project virtual environment not found: $python" }
if (-not $DataDir) { $DataDir = if ($env:JOB_TRACKER_DATA_DIR) { $env:JOB_TRACKER_DATA_DIR } else { Join-Path $root "data" } }
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
$env:JOB_TRACKER_DATA_DIR = (Resolve-Path -LiteralPath $DataDir).Path
$log = Join-Path $env:JOB_TRACKER_DATA_DIR "discovery_worker.log"
& $python (Join-Path $root "scripts\discovery_worker.py") --once *>> $log
exit $LASTEXITCODE

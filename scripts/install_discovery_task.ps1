param(
    [int]$IntervalMinutes = 15,
    [string]$DataDir = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $root "scripts\run_discovery_task.ps1"
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) { throw "Project virtual environment not found: $python" }
if (-not $DataDir) { $DataDir = if ($env:JOB_TRACKER_DATA_DIR) { $env:JOB_TRACKER_DATA_DIR } else { Join-Path $root "data" } }
$taskName = "Job Tracker Discovery"
$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$runner`" -DataDir `"$DataDir`""
schtasks.exe /Create /TN $taskName /SC MINUTE /MO ([Math]::Max(15, $IntervalMinutes)) /TR "powershell.exe $arguments" /F | Out-Host
if ($LASTEXITCODE -ne 0) { throw "Unable to register the Windows task. Exit code $LASTEXITCODE" }
Write-Host "Installed '$taskName' for the current Windows user. Data directory: $DataDir"
Write-Host "Run scripts\uninstall_discovery_task.ps1 to remove it."

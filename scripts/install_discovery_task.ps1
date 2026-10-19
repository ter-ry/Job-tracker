param(
    [int]$IntervalMinutes = 15,
    [string]$DataDir = "",
    [string]$TaskName = "Job Tracker Discovery"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $root "scripts\run_discovery_task.ps1"
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) { throw "Project virtual environment not found: $python" }
if (-not $DataDir) { $DataDir = if ($env:JOB_TRACKER_DATA_DIR) { $env:JOB_TRACKER_DATA_DIR } else { Join-Path $root "data" } }
$DataDir = (New-Item -ItemType Directory -Force -Path $DataDir).FullName
$interval = [Math]::Max(15, $IntervalMinutes)
$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$runner`" -DataDir `"$DataDir`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments
$trigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1)) -RepetitionInterval (New-TimeSpan -Minutes $interval) -RepetitionDuration (New-TimeSpan -Days 3650)
try {
    # Omitting -Principal lets Windows register the task for the current user
    # without requesting the S4U privilege, which is commonly unavailable to
    # standard users. The resulting task uses the current user's credentials.
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Description "Runs the local Job Tracker discovery worker without Flask." -Force | Out-Null
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction Stop
} catch {
    throw "Unable to register Windows task '$TaskName' for '$DataDir'. $($_.Exception.Message)"
}
Write-Host "Installed '$($task.TaskName)' for $($task.Principal.UserId)."
Write-Host "Interval: every $interval minutes"
Write-Host "Data directory: $DataDir"
Write-Host "Next execution: $($info.NextRunTime)"
Write-Host "Run scripts\uninstall_discovery_task.ps1 -TaskName `"$TaskName`" to remove only this task."

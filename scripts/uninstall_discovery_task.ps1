param(
    [string]$TaskName = "Job Tracker Discovery"
)

$ErrorActionPreference = "Stop"
try {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task) { Write-Host "'$TaskName' was not installed."; exit 0 }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
    Write-Host "Removed '$TaskName'."
} catch {
    throw "Unable to remove Windows task '$TaskName'. $($_.Exception.Message)"
}

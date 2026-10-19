$ErrorActionPreference = "Stop"
$taskName = "Job Tracker Discovery"
schtasks.exe /Delete /TN $taskName /F | Out-Host
if ($LASTEXITCODE -eq 0) { Write-Host "Removed '$taskName'." }
elseif ($LASTEXITCODE -eq 1) { Write-Host "'$taskName' was not installed." }
else { throw "Unable to remove the Windows task. Exit code $LASTEXITCODE" }

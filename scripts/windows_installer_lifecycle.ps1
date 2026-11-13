param([Parameter(Mandatory=$true)][string]$Installer)
$ErrorActionPreference = 'Stop'
$root = Join-Path $env:RUNNER_TEMP ([guid]::NewGuid().ToString())
$installDir = Join-Path $root 'install'
$appData = Join-Path $root 'AppData'
$dbPath = Join-Path $appData 'Job Tracker\jobs.sqlite'
$originalAppData = $env:APPDATA
$originalDataDir = $env:JOB_TRACKER_DATA_DIR
$originalExitToken = $env:JOB_TRACKER_EXIT_TOKEN
$env:APPDATA = $appData
Remove-Item Env:JOB_TRACKER_DATA_DIR -ErrorAction SilentlyContinue
$env:JOB_TRACKER_EXIT_TOKEN = [guid]::NewGuid().ToString()
New-Item -ItemType Directory -Force -Path $installDir, $appData | Out-Null
$base = 'http://127.0.0.1:5000'
$appProcess = $null

function Start-InstalledApp {
    $exe = Join-Path $installDir 'JobTracker.exe'
    if (!(Test-Path $exe)) { throw 'Installed JobTracker.exe is missing' }
    $script:appProcess = Start-Process -FilePath $exe -PassThru
    $deadline = (Get-Date).AddSeconds(60)
    $health = $null
    do {
        if ($script:appProcess.HasExited) { throw "Installed app exited with $($script:appProcess.ExitCode)" }
        try { $health = Invoke-RestMethod "$base/api/health" -TimeoutSec 2; break }
        catch { Start-Sleep -Milliseconds 300 }
    } while ((Get-Date) -lt $deadline)
    if (!$health) { throw 'Installed app did not become healthy' }
    $actual = [IO.Path]::GetFullPath([string]$health.database_path)
    if ($actual -ne [IO.Path]::GetFullPath($dbPath)) { throw "Installed app opened unexpected database: $actual" }
    if (!(Test-Path $dbPath)) { throw 'Installed app did not create SQLite database' }
}

function Stop-InstalledApp {
    $headers = @{ 'X-Job-Tracker-Exit-Token' = $env:JOB_TRACKER_EXIT_TOKEN }
    Invoke-RestMethod "$base/api/app/exit" -Method Post -Headers $headers -TimeoutSec 10 | Out-Null
    if (!$script:appProcess.WaitForExit(15000)) { throw 'Installed app did not exit cleanly' }
    if ($script:appProcess.ExitCode -ne 0) { throw "Installed app exited with $($script:appProcess.ExitCode)" }
    $script:appProcess = $null
}

function Install-Package {
    $process = Start-Process -FilePath (Resolve-Path $Installer) -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/DIR=$installDir") -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "Installer failed with exit $($process.ExitCode)" }
}

try {
    Install-Package
    Start-InstalledApp
    $created = Invoke-RestMethod "$base/api/jobs" -Method Post -ContentType 'application/json' -Body '{"company":"Lifecycle Test","title":"Disposable job","status":"Saved"}'
    $jobId = [int]$created.id
    $applied = Invoke-RestMethod "$base/api/jobs/$jobId/applied" -Method Post -ContentType 'application/json' -Body '{}'
    if ($applied.status -ne 'Applied' -or !$applied.date_applied) { throw 'Application status was not saved' }
    $appliedDate = [string]$applied.date_applied
    Stop-InstalledApp
    Install-Package
    if (!(Test-Path $dbPath)) { throw 'Reinstall removed SQLite data' }
    Start-InstalledApp
    $jobs = Invoke-RestMethod "$base/api/jobs"
    $retained = @($jobs) | Where-Object { $_.id -eq $jobId }
    if ($retained.Count -ne 1 -or $retained[0].company -ne 'Lifecycle Test' -or $retained[0].status -ne 'Applied' -or $retained[0].date_applied -ne $appliedDate) {
        throw 'Saved job or application status changed after reinstall'
    }
    Stop-InstalledApp
    $uninstaller = Join-Path $installDir 'unins000.exe'
    if (!(Test-Path $uninstaller)) { throw 'Uninstaller missing' }
    $process = Start-Process -FilePath $uninstaller -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "Uninstall failed with exit $($process.ExitCode)" }
    if (Test-Path (Join-Path $installDir 'JobTracker.exe')) { throw 'Uninstall retained executable' }
    if (!(Test-Path $dbPath)) { throw 'Uninstall removed application SQLite data' }
    Write-Host 'Installed executable: AppData path, saved job, applied status, reinstall and uninstall preservation passed.'
} finally {
    if ($script:appProcess -and !$script:appProcess.HasExited) { Stop-Process -Id $script:appProcess.Id -Force }
    $env:APPDATA = $originalAppData
    if ($null -eq $originalDataDir) { Remove-Item Env:JOB_TRACKER_DATA_DIR -ErrorAction SilentlyContinue } else { $env:JOB_TRACKER_DATA_DIR = $originalDataDir }
    if ($null -eq $originalExitToken) { Remove-Item Env:JOB_TRACKER_EXIT_TOKEN -ErrorAction SilentlyContinue } else { $env:JOB_TRACKER_EXIT_TOKEN = $originalExitToken }
    if ($root -and $root.StartsWith($env:RUNNER_TEMP) -and (Test-Path $root)) { Remove-Item -LiteralPath $root -Recurse -Force }
}

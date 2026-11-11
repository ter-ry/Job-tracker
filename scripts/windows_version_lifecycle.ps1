param(
    [Parameter(Mandatory=$true)][string]$PreviousInstaller,
    [Parameter(Mandatory=$true)][string]$CurrentInstaller,
    [Parameter(Mandatory=$true)][string]$PreviousVersion,
    [Parameter(Mandatory=$true)][string]$CurrentVersion
)
$ErrorActionPreference = 'Stop'
$previousPath = (Resolve-Path $PreviousInstaller).Path
$currentPath = (Resolve-Path $CurrentInstaller).Path
if ($PreviousVersion -eq $CurrentVersion) { throw 'Version lifecycle requires genuinely different application versions' }
$checksumPath = "$previousPath.sha256"
if (!(Test-Path $checksumPath)) { throw 'Historical installer checksum is missing' }
$expectedHash = ((Get-Content $checksumPath -Raw).Trim() -split '\s+')[0]
if ((Get-FileHash $previousPath -Algorithm SHA256).Hash -ne $expectedHash) { throw 'Historical installer checksum mismatch' }
$root = Join-Path $env:RUNNER_TEMP ([guid]::NewGuid().ToString())
$installDir = Join-Path $root 'install'
$appData = Join-Path $root 'AppData'
$dbPath = Join-Path $appData 'Job Tracker\jobs.sqlite'
$base = 'http://127.0.0.1:5000'
$originalAppData = $env:APPDATA
$originalDataDir = $env:JOB_TRACKER_DATA_DIR
$originalExitToken = $env:JOB_TRACKER_EXIT_TOKEN
$env:APPDATA = $appData
Remove-Item Env:JOB_TRACKER_DATA_DIR -ErrorAction SilentlyContinue
$env:JOB_TRACKER_EXIT_TOKEN = [guid]::NewGuid().ToString()
New-Item -ItemType Directory -Force -Path $installDir, $appData | Out-Null
$appProcess = $null

function Install-Version([string]$installer) {
    $process = Start-Process -FilePath $installer -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/DIR=$installDir") -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "Installer failed with exit $($process.ExitCode): $installer" }
}

function Start-Version([string]$expectedVersion) {
    $exe = Join-Path $installDir 'JobTracker.exe'
    if (!(Test-Path $exe)) { throw 'Installed JobTracker.exe is missing' }
    $script:appProcess = Start-Process -FilePath $exe -PassThru
    $deadline = (Get-Date).AddSeconds(60)
    $health = $null
    do {
        if ($script:appProcess.HasExited) { throw "Installed $expectedVersion exited with $($script:appProcess.ExitCode)" }
        try { $health = Invoke-RestMethod "$base/api/health" -TimeoutSec 2; break }
        catch { Start-Sleep -Milliseconds 300 }
    } while ((Get-Date) -lt $deadline)
    if (!$health) { throw "Installed $expectedVersion did not become healthy" }
    $actual = [IO.Path]::GetFullPath([string]$health.database_path)
    if ($actual -ne [IO.Path]::GetFullPath($dbPath)) { throw "Installed app opened unexpected database: $actual" }
    $version = Invoke-RestMethod "$base/api/version" -TimeoutSec 5
    if ($version.version -ne $expectedVersion) { throw "Expected $expectedVersion, got $($version.version)" }
    if (!(Test-Path $dbPath)) { throw 'Installed app did not create SQLite database' }
}

function Stop-Version([bool]$supportsCleanExit) {
    if ($supportsCleanExit) {
        $headers = @{ 'X-Job-Tracker-Exit-Token' = $env:JOB_TRACKER_EXIT_TOKEN }
        $result = Invoke-RestMethod "$base/api/app/exit" -Method Post -Headers $headers -TimeoutSec 10
        if ($result.status -ne 'shutting_down') { throw 'Installed app did not acknowledge clean shutdown' }
        if (!$script:appProcess.WaitForExit(15000)) { throw 'Installed app did not exit cleanly' }
        if ($script:appProcess.ExitCode -ne 0) { throw "Installed app exited with $($script:appProcess.ExitCode)" }
    } else {
        # The historical ci.8 binary has no exit endpoint. Stop only this
        # disposable process after its committed HTTP writes have completed.
        Stop-Process -Id $script:appProcess.Id -Force
        $script:appProcess.WaitForExit(10000) | Out-Null
        Write-Host 'Historical version required forced stop; clean shutdown is untested for that version.'
    }
    $script:appProcess = $null
}

function Assert-Job([int]$jobId, [string]$appliedDate) {
    $jobs = Invoke-RestMethod "$base/api/jobs" -TimeoutSec 10
    $retained = @($jobs) | Where-Object { $_.id -eq $jobId }
    if ($retained.Count -ne 1 -or $retained[0].company -ne 'Version Lifecycle Test' -or $retained[0].status -ne 'Applied' -or $retained[0].date_applied -ne $appliedDate) {
        throw 'Saved job or Applied status changed across installer versions'
    }
}

function Get-SchemaVersion {
    $value = & python -c 'import sqlite3,sys; db=sqlite3.connect(sys.argv[1]); print(db.execute("PRAGMA user_version").fetchone()[0]); db.close()' $dbPath
    if ($LASTEXITCODE -ne 0) { throw 'Could not inspect SQLite schema version' }
    return [int]$value
}

try {
    Install-Version $previousPath
    Start-Version $PreviousVersion
    $created = Invoke-RestMethod "$base/api/jobs" -Method Post -ContentType 'application/json' -Body '{"company":"Version Lifecycle Test","title":"Disposable job","status":"Saved"}'
    $jobId = [int]$created.id
    $applied = Invoke-RestMethod "$base/api/jobs/$jobId/applied" -Method Post -ContentType 'application/json' -Body '{}'
    if ($applied.status -ne 'Applied' -or !$applied.date_applied) { throw 'Old version did not save application status' }
    $appliedDate = [string]$applied.date_applied
    $oldSchema = Get-SchemaVersion
    Stop-Version $false

    Install-Version $currentPath
    Start-Version $CurrentVersion
    Assert-Job $jobId $appliedDate
    $newSchema = Get-SchemaVersion
    if ($newSchema -le $oldSchema) { throw "Expected a real migration, got schema $oldSchema -> $newSchema" }
    $backups = @(Get-ChildItem (Join-Path $appData 'Job Tracker\backups') -Filter 'jobs-before-migration-*.sqlite' -ErrorAction SilentlyContinue)
    if ($backups.Count -lt 1) { throw 'Upgrade did not retain a pre-migration SQLite backup' }
    Stop-Version $true

    # Roll back only in this disposable data root. The older app may reject a
    # newer schema; if so, fail the acceptance test rather than claim support.
    Install-Version $previousPath
    Start-Version $PreviousVersion
    Assert-Job $jobId $appliedDate
    if ((Get-SchemaVersion) -ne $newSchema) { throw 'Rollback changed the upgraded SQLite schema version' }
    Stop-Version $false

    Install-Version $currentPath
    Start-Version $CurrentVersion
    Assert-Job $jobId $appliedDate
    if ((Get-SchemaVersion) -ne $newSchema) { throw 'Re-upgrade changed the SQLite schema version' }
    Stop-Version $true
    Write-Host "Version lifecycle passed: $PreviousVersion (schema $oldSchema) -> $CurrentVersion (schema $newSchema) -> $PreviousVersion -> $CurrentVersion; saved job and Applied status retained."
} finally {
    if ($script:appProcess -and !$script:appProcess.HasExited) { Stop-Process -Id $script:appProcess.Id -Force }
    $env:APPDATA = $originalAppData
    if ($null -eq $originalDataDir) { Remove-Item Env:JOB_TRACKER_DATA_DIR -ErrorAction SilentlyContinue } else { $env:JOB_TRACKER_DATA_DIR = $originalDataDir }
    if ($null -eq $originalExitToken) { Remove-Item Env:JOB_TRACKER_EXIT_TOKEN -ErrorAction SilentlyContinue } else { $env:JOB_TRACKER_EXIT_TOKEN = $originalExitToken }
    if ($root -and $root.StartsWith($env:RUNNER_TEMP) -and (Test-Path $root)) { Remove-Item -LiteralPath $root -Recurse -Force }
}

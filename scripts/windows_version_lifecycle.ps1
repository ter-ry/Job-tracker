param(
    [Parameter(Mandatory=$true)][string]$PreviousInstaller,
    [Parameter(Mandatory=$true)][string]$CurrentInstaller,
    [Parameter(Mandatory=$true)][string]$RollbackInstaller,
    [Parameter(Mandatory=$true)][string]$PreviousVersion,
    [Parameter(Mandatory=$true)][string]$CurrentVersion,
    [Parameter(Mandatory=$true)][string]$RollbackVersion,
    [Parameter(Mandatory=$true)][int]$RollbackSchemaVersion
)
$ErrorActionPreference = 'Stop'
$script:Phase = 'initialization'
$script:InstallerTimeoutSeconds = 120

function Set-Phase([string]$name) {
    $script:Phase = $name
    Write-Host "[lifecycle] $name"
}

function Stop-ProcessTree([System.Diagnostics.Process]$process, [string]$reason) {
    if ($null -eq $process -or $process.HasExited) { return }
    Write-Warning "Stopping process $($process.Id) after $reason"
    $killer = Start-Process -FilePath 'taskkill.exe' -ArgumentList @('/PID', $process.Id, '/T', '/F') -PassThru
    if (!$killer.WaitForExit(10000)) {
        Write-Warning "taskkill did not finish within 10 seconds for PID $($process.Id)"
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
    if (!$process.HasExited) { $process.WaitForExit(10000) | Out-Null }
}

function Invoke-Installer([string]$installer, [string]$label) {
    Set-Phase "install $label"
    Write-Host "[lifecycle] installer=$installer target=$installDir timeout=${script:InstallerTimeoutSeconds}s"
    $process = Start-Process -FilePath $installer -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/DIR=$installDir") -PassThru
    if (!$process.WaitForExit($script:InstallerTimeoutSeconds * 1000)) {
        Stop-ProcessTree $process 'installer timeout'
        throw "Installer timed out after $($script:InstallerTimeoutSeconds) seconds: $installer"
    }
    Write-Host "[lifecycle] installer exit=$($process.ExitCode)"
    if ($process.ExitCode -ne 0) { throw "Installer failed with exit $($process.ExitCode): $installer" }
}
$previousPath = (Resolve-Path $PreviousInstaller).Path
$currentPath = (Resolve-Path $CurrentInstaller).Path
$rollbackPath = (Resolve-Path $RollbackInstaller).Path
if ($PreviousVersion -eq $CurrentVersion -or $RollbackVersion -eq $CurrentVersion -or $PreviousVersion -eq $RollbackVersion) { throw 'Version lifecycle requires three genuinely different application versions' }
$checksumPath = "$previousPath.sha256"
if (!(Test-Path $checksumPath)) { throw 'Historical installer checksum is missing' }
$expectedHash = ((Get-Content $checksumPath -Raw).Trim() -split '\s+')[0]
if ((Get-FileHash $previousPath -Algorithm SHA256).Hash -ne $expectedHash) { throw 'Historical installer checksum mismatch' }
$rollbackChecksumPath = "$rollbackPath.sha256"
if (!(Test-Path $rollbackChecksumPath)) { throw 'Rollback installer checksum is missing' }
$expectedRollbackHash = ((Get-Content $rollbackChecksumPath -Raw).Trim() -split '\s+')[0]
if ((Get-FileHash $rollbackPath -Algorithm SHA256).Hash -ne $expectedRollbackHash) { throw 'Rollback installer checksum mismatch' }
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

function Start-Version([string]$expectedVersion) {
    Set-Phase "start $expectedVersion"
    $exe = Join-Path $installDir 'JobTracker.exe'
    if (!(Test-Path $exe)) { throw 'Installed JobTracker.exe is missing' }
    $script:appProcess = Start-Process -FilePath $exe -PassThru
    $deadline = (Get-Date).AddSeconds(60)
    $health = $null
    $attempts = 0
    do {
        $attempts++
        if ($script:appProcess.HasExited) { throw "Installed $expectedVersion exited with $($script:appProcess.ExitCode)" }
        try { $health = Invoke-RestMethod "$base/api/health" -TimeoutSec 2; break }
        catch { Start-Sleep -Milliseconds 300 }
    } while ((Get-Date) -lt $deadline)
    if (!$health) { throw "Installed $expectedVersion did not become healthy after $attempts probes in 60 seconds" }
    $actual = [IO.Path]::GetFullPath([string]$health.database_path)
    if ($actual -ne [IO.Path]::GetFullPath($dbPath)) { throw "Installed app opened unexpected database: $actual" }
    $version = Invoke-RestMethod "$base/api/version" -TimeoutSec 5
    if ($version.version -ne $expectedVersion) { throw "Expected $expectedVersion, got $($version.version)" }
    if (!(Test-Path $dbPath)) { throw 'Installed app did not create SQLite database' }
    Write-Host "[lifecycle] healthy version=$($version.version) database=$actual probes=$attempts pid=$($script:appProcess.Id)"
}

function Stop-Version([bool]$supportsCleanExit) {
    Set-Phase "stop process $($script:appProcess.Id) clean=$supportsCleanExit"
    if ($supportsCleanExit) {
        $headers = @{ 'X-Job-Tracker-Exit-Token' = $env:JOB_TRACKER_EXIT_TOKEN }
        $result = Invoke-RestMethod "$base/api/app/exit" -Method Post -Headers $headers -TimeoutSec 10
        if ($result.status -ne 'shutting_down') { throw 'Installed app did not acknowledge clean shutdown' }
        if (!$script:appProcess.WaitForExit(15000)) { throw 'Installed app did not exit cleanly' }
        if ($script:appProcess.ExitCode -ne 0) { throw "Installed app exited with $($script:appProcess.ExitCode)" }
    } else {
        # The historical ci.8 binary has no exit endpoint. Stop only this
        # disposable process after its committed HTTP writes have completed.
        Stop-ProcessTree $script:appProcess 'historical binary has no clean-exit endpoint'
        Write-Host 'Historical version required forced stop; clean shutdown is untested for that version.'
    }
    $script:appProcess = $null
}

function Assert-Job([int]$jobId, [string]$appliedDate) {
    Set-Phase "verify persisted job $jobId"
    $jobs = Invoke-RestMethod "$base/api/jobs" -TimeoutSec 10
    $retained = @($jobs) | Where-Object { $_.id -eq $jobId }
    if ($retained.Count -ne 1 -or $retained[0].company -ne 'Version Lifecycle Test' -or $retained[0].status -ne 'Applied' -or $retained[0].date_applied -ne $appliedDate) {
        throw 'Saved job or Applied status changed across installer versions'
    }
}

function Get-SchemaVersion {
    Set-Phase 'inspect SQLite schema'
    $value = & python -c 'import sqlite3,sys; db=sqlite3.connect(sys.argv[1]); print(db.execute("PRAGMA user_version").fetchone()[0]); db.close()' $dbPath
    if ($LASTEXITCODE -ne 0) { throw 'Could not inspect SQLite schema version' }
    return [int]$value
}

try {
    Write-Host "[lifecycle] root=$root install=$installDir appdata=$appData db=$dbPath"
    Invoke-Installer $previousPath $PreviousVersion
    Start-Version $PreviousVersion
    Set-Phase 'create and apply sentinel job'
    $created = Invoke-RestMethod "$base/api/jobs" -Method Post -TimeoutSec 10 -ContentType 'application/json' -Body '{"company":"Version Lifecycle Test","title":"Disposable job","status":"Saved"}'
    $jobId = [int]$created.id
    $applied = Invoke-RestMethod "$base/api/jobs/$jobId/applied" -Method Post -TimeoutSec 10 -ContentType 'application/json' -Body '{}'
    if ($applied.status -ne 'Applied' -or !$applied.date_applied) { throw 'Old version did not save application status' }
    $appliedDate = [string]$applied.date_applied
    $oldSchema = Get-SchemaVersion
    Stop-Version $false

    Invoke-Installer $currentPath $CurrentVersion
    Start-Version $CurrentVersion
    Assert-Job $jobId $appliedDate
    $newSchema = Get-SchemaVersion
    if ($newSchema -le $oldSchema) { throw "Expected a real migration, got schema $oldSchema -> $newSchema" }
    $backups = @(Get-ChildItem (Join-Path $appData 'Job Tracker\backups') -Filter 'jobs-before-migration-*.sqlite' -ErrorAction SilentlyContinue)
    if ($backups.Count -lt 1) { throw 'Upgrade did not retain a pre-migration SQLite backup' }
    Stop-Version $true

    # Only execute an older binary when its declared schema matches the newly
    # migrated database. Older builds rewrite PRAGMA user_version during
    # startup, so probing an incompatible binary would itself damage the test
    # database rather than safely demonstrating rollback behavior.
    $rollbackTested = $false
    if ($RollbackSchemaVersion -eq $newSchema) {
        Invoke-Installer $rollbackPath $RollbackVersion
        Start-Version $RollbackVersion
        Assert-Job $jobId $appliedDate
        if ((Get-SchemaVersion) -ne $newSchema) { throw 'Rollback changed the upgraded SQLite schema version' }
        Stop-Version $true
        $rollbackTested = $true
    } else {
        Write-Host "Compatible rollback skipped: $RollbackVersion declares schema $RollbackSchemaVersion but current uses schema $newSchema."
    }

    Invoke-Installer $currentPath $CurrentVersion
    Start-Version $CurrentVersion
    Assert-Job $jobId $appliedDate
    if ((Get-SchemaVersion) -ne $newSchema) { throw 'Re-upgrade changed the SQLite schema version' }
    Stop-Version $true
    $rollbackSummary = if ($rollbackTested) { "$RollbackVersion (schema $RollbackSchemaVersion)" } else { "no compatible historical binary" }
    Write-Host "Version lifecycle passed: $PreviousVersion (schema $oldSchema) -> $CurrentVersion (schema $newSchema) -> $rollbackSummary -> $CurrentVersion; saved job and Applied status retained. Unsafe rollback binaries were not started."
} finally {
    Set-Phase "cleanup after $script:Phase"
    if ($script:appProcess -and !$script:appProcess.HasExited) { Stop-ProcessTree $script:appProcess 'lifecycle cleanup' }
    $env:APPDATA = $originalAppData
    if ($null -eq $originalDataDir) { Remove-Item Env:JOB_TRACKER_DATA_DIR -ErrorAction SilentlyContinue } else { $env:JOB_TRACKER_DATA_DIR = $originalDataDir }
    if ($null -eq $originalExitToken) { Remove-Item Env:JOB_TRACKER_EXIT_TOKEN -ErrorAction SilentlyContinue } else { $env:JOB_TRACKER_EXIT_TOKEN = $originalExitToken }
    if ($root -and $root.StartsWith($env:RUNNER_TEMP) -and (Test-Path $root)) {
        try {
            Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction Stop
            Write-Host "[lifecycle] cleanup removed $root"
        } catch {
            Write-Warning "Cleanup could not remove ${root}: $($_.Exception.Message)"
        }
    }
}

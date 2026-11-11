param([Parameter(Mandatory=$true)][string]$Installer)
$ErrorActionPreference = 'Stop'
$root = Join-Path $env:RUNNER_TEMP ([guid]::NewGuid().ToString())
$installDir = Join-Path $root 'install'
$dataDir = Join-Path $root 'AppData\Job Tracker'
New-Item -ItemType Directory -Force -Path $installDir, $dataDir | Out-Null
$sentinel = Join-Path $dataDir 'preserve-test.txt'
Set-Content -Path $sentinel -Value 'preserve' -NoNewline
try {
    foreach ($phase in @('install', 'reinstall')) {
        $process = Start-Process -FilePath (Resolve-Path $Installer) -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/DIR=$installDir") -Wait -PassThru
        if ($process.ExitCode -ne 0) { throw "$phase failed with exit $($process.ExitCode)" }
        if (!(Test-Path (Join-Path $installDir 'JobTracker.exe'))) { throw "$phase did not install JobTracker.exe" }
        if (!(Test-Path $sentinel)) { throw "$phase removed AppData sentinel" }
    }
    $uninstaller = Join-Path $installDir 'unins000.exe'
    if (!(Test-Path $uninstaller)) { throw 'Uninstaller missing' }
    $process = Start-Process -FilePath $uninstaller -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "Uninstall failed with exit $($process.ExitCode)" }
    if (Test-Path (Join-Path $installDir 'JobTracker.exe')) { throw 'Uninstall retained executable' }
    if (!(Test-Path $sentinel)) { throw 'Uninstall removed AppData sentinel' }
    Write-Host 'Disposable install, reinstall, uninstall and AppData preservation passed.'
} finally {
    Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
}

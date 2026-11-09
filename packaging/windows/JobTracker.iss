#define AppName "Job Tracker"
#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif

[Setup]
AppId={{F6E8D7A7-0C18-49DC-8B49-4B3A88FC6C75}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=ter-ry
DefaultDirName={autopf}\Job Tracker
DefaultGroupName={#AppName}
OutputBaseFilename=JobTracker-Setup-v{#AppVersion}
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
Uninstallable=yes
; AppMutex prevents the installer from replacing files while the app runs.
AppMutex=JobTrackerInstance

[Files]
Source: "dist\JobTracker\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\JobTracker.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\JobTracker.exe"

[Run]
Filename: "{app}\JobTracker.exe"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Deliberately do not remove {userappdata}\Job Tracker. User data survives
; uninstall/reinstall and is backed up by the application before migrations.

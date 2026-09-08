; ============================================================================
;  Arena Windows Computer Agent — Installer (Inno Setup)
;  Build:  iscc install_windows.iss   (or via the GUI)
;  Produces a Windows installer that sets up the Local Agent as a desktop app,
;  installs the Python deps, and registers it to optionally start with Windows.
; ============================================================================

#define AppName "Arena Windows Agent"
#define AppVersion "2.0.0"
#define AppPublisher "Arena"
#define AppExeName "ArenaAgent.exe"

[Setup]
AppId={{D0A0F3C6-1B2E-4A7D-9C1F-5E8B2A6D4C1E}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
OutputDir=output
OutputBaseFilename=ArenaWindowsAgent-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "arabic"; MessagesFile: "compiler:Languages\Arabic.isl"

[Tasks]
Name: "startup"; Description: "ابدأ تلقائيًا مع Windows"; GroupDescription: "تشغيل تلقائي:"; Flags: unchecked

[Files]
Source: "..\run.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\desktop_app.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\agent_platform\*.py"; DestDir: "{app}\agent_platform"; Flags: ignoreversion recursesubdirs
Source: "..\browser-extension\*"; DestDir: "{app}\browser-extension"; Flags: ignoreversion recursesubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\ArenaAgent.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\ArenaAgent.exe"; WorkingDir: "{app}"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; \
  ValueName: "ArenaAgent"; ValueData: """{app}\ArenaAgent.exe"""; Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\RunInstaller.bat"; Description: "إعداد البيئة (تثبيت المتطلبات)"; Flags: runhidden
Filename: "{app}\ArenaAgent.exe"; Description: "تشغيل الوكيل"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /IM ArenaAgent.exe /F"; Flags: runhidden skipifdoesntexist

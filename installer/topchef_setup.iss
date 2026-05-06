; ══════════════════════════════════════════════════════════════
; Top Chef Desktop POS — Inno Setup Installer Script
; ══════════════════════════════════════════════════════════════
; Compile with:  ISCC.exe topchef_setup.iss
; Requires:      Inno Setup 6+  (https://jrsoftware.org)
; ══════════════════════════════════════════════════════════════

#define MyAppName      "Top Chef POS"
#define MyAppVersion   "1.0.0"
#define MyAppPublisher "Top Chef"
#define MyAppExeName   "TopChef.exe"
#define MyAppURL       "https://topchef-system.fastapicloud.dev"

; Path to PyInstaller output (relative to this .iss file)
#define DistDir        "..\build\dist\TopChef"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=output
OutputBaseFilename=TopChefSetup_{#MyAppVersion}
SetupIconFile={#DistDir}\assets\icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
DisableProgramGroupPage=yes
; Minimum Windows 10
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
; Arabic support (if Inno Setup Arabic translation is installed)
; Name: "arabic"; MessagesFile: "compiler:Languages\Arabic.isl"

[Tasks]
Name: "desktopicon";   Description: "{cm:CreateDesktopIcon}";   GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "quicklaunchicon"; Description: "{cm:CreateQuickLaunchIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked; OnlyBelowVersion: 6.1; Check: not IsAdminInstallMode
Name: "autostart";     Description: "تشغيل تلقائي عند بدء Windows / Start with Windows"; GroupDescription: "خيارات إضافية / Additional Options"; Flags: unchecked

[Files]
; Main application files (from PyInstaller dist)
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; Ensure writable data directories exist
Source: "{#DistDir}\data\*";   DestDir: "{app}\data";   Flags: ignoreversion recursesubdirs createallsubdirs; Permissions: users-modify
Source: "{#DistDir}\logs\*";   DestDir: "{app}\logs";   Flags: ignoreversion recursesubdirs createallsubdirs; Permissions: users-modify

[Icons]
Name: "{group}\{#MyAppName}";                   Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}";             Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: quicklaunchicon

[Registry]
; Auto-start with Windows (optional task)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "TopChefPOS"; ValueData: """{app}\{#MyAppExeName}"""; \
    Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Clean up user data on uninstall (optional — user may want to keep data)
; Type: filesandordirs; Name: "{app}\data"
; Type: filesandordirs; Name: "{app}\logs"

[Code]
// ── Pre-install: close running instance ──
function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  // Try to close any running instance
  Exec('taskkill', '/F /IM {#MyAppExeName}', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := True;
end;

// ── Post-install: set data folder permissions ──
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    // Grant users write access to data and logs folders
    Exec('icacls', '"' + ExpandConstant('{app}\data') + '" /grant Users:(OI)(CI)F', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Exec('icacls', '"' + ExpandConstant('{app}\logs') + '" /grant Users:(OI)(CI)F', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;

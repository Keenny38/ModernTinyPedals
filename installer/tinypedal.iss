; Modern Tiny Pedals Windows installer (Inno Setup 6)
;
; Build after PyInstaller (python build_pyinstaller.py -c):
;   iscc /DAppVersion=2.50.0 installer\tinypedal.iss
;
; Installs per user in %LOCALAPPDATA%\Programs\Modern Tiny Pedals (no admin rights),
; because the app keeps presets & user data next to the executable.
; Updating keeps all user files; uninstalling only removes installed files.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Modern Tiny Pedals"
; PyInstaller output folder (dist\TinyPedal), internal name kept for user data
#define AppFolder "TinyPedal"
#define AppExe "tinypedal.exe"
#define RepoUrl "https://github.com/Keenny38/overlays"

[Setup]
AppId={{6C3F5B8E-4A2D-4E1B-9C7A-1D2E3F4A5B6C}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=TinyPedal developers
AppPublisherURL={#RepoUrl}
AppSupportURL={#RepoUrl}/issues
AppUpdatesURL={#RepoUrl}/releases
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
LicenseFile=..\LICENSE.txt
OutputDir=..\dist
OutputBaseFilename=ModernTinyPedals-{#AppVersion}-windows-setup
SetupIconFile=..\images\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\{#AppFolder}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall

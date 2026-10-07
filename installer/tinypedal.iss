; Modern Tiny Pedals Windows installer (Inno Setup 6)
;
; Build after PyInstaller (python build_pyinstaller.py -c):
;   iscc /DAppVersion=0.10.0 installer\tinypedal.iss
;
; Installs per user in %LOCALAPPDATA%\Programs\Modern Tiny Pedals (no admin rights),
; because the app keeps presets & user data next to the executable.
; Updating keeps all user files; uninstalling only removes installed files, and the OpenXR layer registration
; the app adds for the VR overlay (HKCU, see tinypedal/vr_shared.py).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Modern Tiny Pedals"
; PyInstaller output folder (dist\TinyPedal), internal name kept for user data
#define AppFolder "TinyPedal"
#define AppExe "tinypedal.exe"
#define RepoUrl "https://github.com/Keenny38/ModernTinyPedals"

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
; Only processes running a replaced executable (the app). OpenXR games load the layer DLL, never from the
; files replaced here (copied by the app to {app}\openxr_layer, see below): never closed by an update.
CloseApplicationsFilter=*.exe
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Program files of previous version: lib is rebuilt by each release (Python, Qt & QML modules change),
; stale files would pile up. User data (presets, telemetry...) is next to the executable, not in lib.
Type: filesandordirs; Name: "{app}\lib"
; Example speed plugin, shipped until 0.21: removed from the app (plugins added by user are kept)
Type: filesandordirs; Name: "{app}\plugins\example_speed"

[Files]
Source: "..\dist\{#AppFolder}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[UninstallDelete]
; OpenXR layer copies made by the app (one folder per layer build, outside lib so updates never touch a DLL
; loaded by a game). A copy still loaded by a running game stays until removed by hand.
Type: filesandordirs; Name: "{app}\openxr_layer"

[Icons]
; Shortcut icon matches Windows light / dark mode at install time (white & gold icon when dark)
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Check: not IsDarkMode
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; IconFilename: "{app}\images\icon_dark.ico"; Check: IsDarkMode
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: desktopicon; Check: not IsDarkMode
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; IconFilename: "{app}\images\icon_dark.ico"; Tasks: desktopicon; Check: IsDarkMode

[Run]
Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall

[Code]
// Windows taskbar & Start menu in dark mode (same setting as app icon at runtime)
function IsDarkMode: Boolean;
var
  LightTheme: Cardinal;
begin
  Result := RegQueryDWordValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize',
    'SystemUsesLightTheme', LightTheme) and (LightTheme = 0);
end;

// VR overlay: the app copies its OpenXR layer from lib\openxr_layer_bundle to {app}\openxr_layer\<build>\ and
// registers that TinyPedalXrLayer.json for the current user (older versions: lib\openxr_layer, same cleanup).
// Removed on uninstall: OpenXR games must never look for a layer whose files are gone.
const
  OpenXRLayersKey = 'SOFTWARE\Khronos\OpenXR\1\ApiLayers\Implicit';

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Names: TArrayOfString;
  AppPath, Name: String;
  I: Integer;
begin
  if CurUninstallStep <> usUninstall then
    exit;
  AppPath := Lowercase(AddBackslash(ExpandConstant('{app}')));
  if RegGetValueNames(HKCU, OpenXRLayersKey, Names) then
    for I := 0 to GetArrayLength(Names) - 1 do
    begin
      Name := Lowercase(Names[I]);
      if (Pos(AppPath, Name) = 1) and (Pos('tinypedalxrlayer.json', Name) > 0) then
        RegDeleteValue(HKCU, OpenXRLayersKey, Names[I]);
    end;
end;

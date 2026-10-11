; NeoPedal Windows installer (Inno Setup 6)
;
; Build after PyInstaller (python build_pyinstaller.py -c):
;   iscc /DAppVersion=0.10.0 installer\neopedal.iss
;
; Installs per user in %LOCALAPPDATA%\Programs\NeoPedal (no admin rights; updates keep the folder of an
; older install, such as Programs\Modern Tiny Pedals),
; because the app keeps presets & user data next to the executable.
; Updating keeps all user files; uninstalling only removes installed files, and the OpenXR layer registration
; the app adds for the VR overlay (HKCU, see neopedal/vr_shared.py).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "NeoPedal"
; PyInstaller output folder (dist\NeoPedal) & executable
#define AppFolder "NeoPedal"
#define AppExe "neopedal.exe"
; Name of versions until 0.23.0 (neopedal/const_app.py LEGACY_NAME): old executable & VR layer removed
#define LegacyName "tinypedal"
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
OutputBaseFilename=NeoPedal-{#AppVersion}-windows-setup
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
; Executable of versions until 0.23.0, renamed neopedal.exe (shortcuts below point to the new name)
Type: files; Name: "{app}\{#LegacyName}.exe"
; Shortcuts named "Modern Tiny Pedals" before the NeoPedal name (Start menu folder keeps its name on update)
Type: files; Name: "{group}\Modern Tiny Pedals.lnk"
Type: files; Name: "{userdesktop}\Modern Tiny Pedals.lnk"
Type: files; Name: "{group}\{cm:UninstallProgram,Modern Tiny Pedals}.lnk"
; Example speed plugin, shipped until 0.21: removed from the app (plugins added by user are kept)
Type: filesandordirs; Name: "{app}\plugins\example_speed"

[Files]
Source: "..\dist\{#AppFolder}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[UninstallDelete]
; OpenXR layer copies made by the app (one folder per layer build, outside lib so updates never touch a DLL
; loaded by a game). A copy still loaded by a running game stays until removed by hand.
Type: filesandordirs; Name: "{app}\openxr_layer"
; Copies to an ASCII folder when the app folder has non-ASCII characters (OpenXR loader reads ANSI paths);
; copies in %PUBLIC% or at the system drive root removed by CurUninstallStepChanged (below)
Type: filesandordirs; Name: "{commonappdata}\ModernTinyPedals\openxr_layer"

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
// registers that NeoPedalXrLayer.json for the current user (older versions: lib\openxr_layer, same cleanup).
// Non-ASCII app folder: registered by its 8.3 short path, or copied to the first writable ASCII folder of
// neopedal/vr_shared.py ascii_layer_roots: {commonappdata}, %PUBLIC% or system drive root, each followed by
// ModernTinyPedals\openxr_layer\<user>\<build>\.
// Removed on uninstall (after files are deleted): OpenXR games must never look for a layer whose files are gone.
const
  OpenXRLayersKey = 'SOFTWARE\Khronos\OpenXR\1\ApiLayers\Implicit';
  LayerCopyFolder = 'ModernTinyPedals\openxr_layer\';

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Names, Roots: TArrayOfString;
  Name: String;
  I, J: Integer;
  Remove: Boolean;
begin
  if CurUninstallStep <> usPostUninstall then
    exit;
  // Index 0: install folder (files already deleted), 1-3: ASCII copy folders (all users' copies removed)
  SetArrayLength(Roots, 4);
  Roots[0] := AddBackslash(ExpandConstant('{app}'));
  Roots[1] := AddBackslash(ExpandConstant('{commonappdata}')) + LayerCopyFolder;
  Roots[2] := '';
  if GetEnv('PUBLIC') <> '' then
    Roots[2] := AddBackslash(GetEnv('PUBLIC')) + LayerCopyFolder;
  Roots[3] := AddBackslash(ExpandConstant('{sd}')) + LayerCopyFolder;
  for J := 1 to 3 do
    if Roots[J] <> '' then
    begin
      // A copy still loaded by a running game stays until removed by hand
      DelTree(RemoveBackslash(Roots[J]), True, True, True);
      RemoveDir(ExtractFileDir(RemoveBackslash(Roots[J])));  // ModernTinyPedals folder, only if empty
    end;
  if RegGetValueNames(HKCU, OpenXRLayersKey, Names) then
    for I := 0 to GetArrayLength(Names) - 1 do
    begin
      Name := Lowercase(Names[I]);
      Remove := not FileExists(Names[I]);
      for J := 0 to 3 do
        if (Roots[J] <> '') and (Pos(Lowercase(Roots[J]), Name) = 1) then
          Remove := True;
      if ((Pos('neopedalxrlayer.json', Name) > 0) or (Pos('{#LegacyName}xrlayer.json', Name) > 0)) and Remove then
        RegDeleteValue(HKCU, OpenXRLayersKey, Names[I]);
    end;
end;

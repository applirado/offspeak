; OffSpeak installer (Inno Setup 6). Built by .github/workflows/release.yml:
;   iscc /DAppVersion=0.1.0 installer\offspeak.iss
; expects the uv binary in build\uv\uv.exe. The installer copies OffSpeak, then setup.ps1 -Installer
; downloads Python, the packages and the voice model into the same folder.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F3B2A41-8C5E-4D8B-9E2A-0FF5EA4C0D17}
AppName=OffSpeak
AppVersion={#AppVersion}
AppPublisher=Applirado
AppPublisherURL=https://applirado.github.io/offspeak/
AppSupportURL=https://github.com/applirado/offspeak/issues
AppUpdatesURL=https://github.com/applirado/offspeak/releases
DefaultDirName={autopf}\OffSpeak
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=OffSpeak-Setup-{#AppVersion}
SetupIconFile=..\assets\offspeak.ico
UninstallDisplayIcon={app}\offspeak.ico
UninstallDisplayName=OffSpeak
LicenseFile=..\LICENSE
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
CloseApplications=no

[Tasks]
Name: "autostart"; Description: "Start OffSpeak when I sign in to Windows"

[Files]
Source: "..\src\offspeak\*"; DestDir: "{app}\src\offspeak"; Excludes: "__pycache__"; Flags: recursesubdirs ignoreversion
Source: "..\pyproject.toml"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\uv.lock"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\setup.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\assets\offspeak.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\build\uv\uv.exe"; DestDir: "{app}\bin"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\OffSpeak"; Filename: "{app}\.venv\Scripts\offspeakw.exe"; Parameters: "run"; WorkingDir: "{app}"; IconFilename: "{app}\offspeak.ico"; Comment: "Offline voice dictation"

[Registry]
; same value the app's Startup setting and "offspeak autostart" read and write
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Offspeak"; ValueData: """{app}\.venv\Scripts\offspeakw.exe"" run"; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\.venv\Scripts\offspeakw.exe"; Parameters: "run"; Description: "Start OffSpeak now"; Flags: postinstall nowait skipifsilent; Check: AppReady

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\src"
Type: dirifempty; Name: "{app}"

[Code]
procedure StopOffSpeak();
var
  Code: Integer;
begin
  { only Python and the launcher from this folder; the uninstaller itself also lives here }
  Exec('powershell.exe',
    '-NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -match ''^(python|pythonw|offspeak|offspeakw)\.exe$'' -and $_.CommandLine -like ''*' +
    ExpandConstant('{app}') + '*'' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"',
    '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

function AppReady(): Boolean;
begin
  Result := FileExists(ExpandConstant('{app}\.venv\Scripts\offspeakw.exe'));
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopOffSpeak();  { an update replaces files the running app holds open }
  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Code: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    WizardForm.StatusLabel.Caption := 'Downloading Python, the packages and the voice model (about 1 GB). This takes a few minutes...';
    if not Exec('powershell.exe',
         '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\setup.ps1') + '" -Installer',
         ExpandConstant('{app}'), SW_SHOWNORMAL, ewWaitUntilTerminated, Code) or (Code <> 0) then
      MsgBox('OffSpeak could not download everything it needs (error ' + IntToStr(Code) + ').' + #13#10 + #13#10 +
        'Check your internet connection and run the setup again; it continues where it stopped.',
        mbError, MB_OK);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Data: String;
begin
  if CurUninstallStep = usUninstall then
    StopOffSpeak();
  if CurUninstallStep = usPostUninstall then
  begin
    Data := ExpandConstant('{localappdata}\Offspeak');
    if DirExists(Data) and not UninstallSilent() and
       (MsgBox('Also delete your settings, dictation history and downloaded voice models?' + #13#10 + #13#10 + Data,
          mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES) then
      DelTree(Data, True, True, True);
  end;
end;

; POE2 Sentinel - Inno Setup Installer Script
; Bundles the app + Tesseract OCR engine for the OCR fallback mode.
; The entity overlay (PyQt5) and Shader Reveal (.NET/LibGGPK3) ship inside the
; PyInstaller _internal folder, which is copied recursively below (libggpk DLLs
; land in _internal\libggpk). Shader Reveal additionally needs the .NET runtime
; on the target PC; without it that one feature degrades gracefully.

#define MyAppName "POE2 Sentinel"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Ace047"
#define MyAppExeName "POE2Sentinel.exe"

[Setup]
AppId={{C8E3D2B5-4G67-5E90-0BCD-2233445566BB}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=..\dist
OutputBaseFilename=POE2Sentinel_Setup_v{#MyAppVersion}
SetupIconFile=..\POE2-Sentinel-Icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Main executable and PyInstaller dependencies
Source: "..\dist\POE2Sentinel\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\POE2Sentinel\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

; Tesseract OCR engine (bundled for OCR fallback mode)
#ifexist SourcePath + "..\tesseract-portable\tesseract.exe"
Source: "..\tesseract-portable\*"; DestDir: "{app}\tesseract"; Flags: ignoreversion recursesubdirs createallsubdirs
#endif

; Readme
Source: "RELEASE_README.txt"; DestDir: "{app}"; DestName: "README.txt"; Flags: ignoreversion isreadme

; Icon
Source: "..\POE2-Sentinel-Icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\POE2-Sentinel-Icon.ico"
Name: "{group}\README"; Filename: "{app}\README.txt"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\POE2-Sentinel-Icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

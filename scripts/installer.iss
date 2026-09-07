#define MyAppName "PalModManager"
#define MyAppNameCN "帕鲁Mod管理器"
#define MyAppVersion "1.2.12"
#define MyAppPublisher "muqing12320"
#define MyAppExeName "PalModManager.WinUI.exe"
#define MyAppIcon "..\PalModManager.WinUI\PalModManager.WinUI\Assets\AppIcon.ico"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppNameCN}
AppVersion={#MyAppVersion}
AppVerName={#MyAppNameCN} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppNameCN}
DisableProgramGroupPage=yes
OutputDir=..\build\installer
OutputBaseFilename=PalModManager-Setup
SetupIconFile={#MyAppIcon}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#MyAppNameCN}

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; src\ui held the old PyQt5 interface; it no longer ships, so clear it out on upgrade
Type: filesandordirs; Name: "{app}\src\ui"

[Files]
Source: "..\build\winui\app\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.pdb,__pycache__\*"

[Icons]
Name: "{group}\{#MyAppNameCN}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppNameCN}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; IconFilename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppNameCN}}"; Flags: nowait postinstall

[UninstallDelete]
; AppData - config, profiles, backups
Type: files; Name: "{userappdata}\帕鲁Mod管理器\config.json"
Type: files; Name: "{userappdata}\帕鲁Mod管理器\profiles.json"
Type: files; Name: "{userappdata}\帕鲁Mod管理器\profiles_*.json"
Type: files; Name: "{userappdata}\帕鲁Mod管理器\backups_*\*"
Type: dirifempty; Name: "{userappdata}\帕鲁Mod管理器"
; Install dir - Python bytecode caches
Type: files; Name: "{app}\src\__pycache__\*"
Type: dirifempty; Name: "{app}\src\__pycache__"
Type: files; Name: "{app}\src\backend\__pycache__\*"
Type: dirifempty; Name: "{app}\src\backend\__pycache__"
Type: files; Name: "{app}\src\core\__pycache__\*"
Type: dirifempty; Name: "{app}\src\core\__pycache__"
Type: files; Name: "{app}\src\services\__pycache__\*"
Type: dirifempty; Name: "{app}\src\services\__pycache__"
Type: files; Name: "{app}\src\utils\__pycache__\*"
Type: dirifempty; Name: "{app}\src\utils\__pycache__"
; Temp update leftovers
Type: files; Name: "{tmp}\PalModManagerUpdate\*"
Type: dirifempty; Name: "{tmp}\PalModManagerUpdate"

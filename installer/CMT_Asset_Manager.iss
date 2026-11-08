#define AppName "CMT Asset Manager"
#define AppVersion "1.1.2"
#define AppExe "CMTAssetManager.exe"

[Setup]
AppId={{87D0CCAC-9B66-4FC4-ADDA-77924749D04D}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Cyber Matt Technologies
AppPublisherURL=https://cybermatt.tech
VersionInfoVersion=1.1.2.0
DefaultDirName={localappdata}\Programs\CMT Asset Manager
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\output
OutputBaseFilename=CMT_Asset_Manager_Setup_1.1.2
SetupIconFile=..\assets\cmt.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
AppMutex=Local\CMTAssetManagerDesktop
CloseApplications=no
RestartApplications=no
SetupLogging=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: checkedonce

[Files]
Source: "..\dist\CMTAssetManager\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\USER_GUIDE.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; AppUserModelID: "CyberMattTechnologies.CMTAssetManager"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: desktopicon; AppUserModelID: "CyberMattTechnologies.CMTAssetManager"
Name: "{group}\Recover administrator password"; Filename: "{app}\{#AppExe}"; Parameters: "--recover-admin"; WorkingDir: "{app}"
Name: "{group}\User guide"; Filename: "{app}\USER_GUIDE.txt"

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

; Data is outside {app}. Uninstall never removes inventory or user uploads.

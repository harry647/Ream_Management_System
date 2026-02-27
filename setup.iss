; Inno Setup Script for Ream Management System
[Setup]
AppName=Ream Management System
AppVersion=1.0.0
AppPublisher=HarLuFran InnoFlux Computing
AppSupportURL=https://harlufraninnoflux.co.ke
AppUpdatesURL=https://harlufraninnoflux.co.ke
DefaultDirName={autopf}\ReamManagement
DefaultGroupName=Ream Management
OutputDir=dist
OutputBaseFilename=ReamManagementSetup
Compression=lzma2
SolidCompression=yes
SetupIconFile=icons\login.ico
WizardStyle=modern
PrivilegesRequired=low
AllowNoIcons=yes
WizardImageFile=installer_banner.bmp
WizardSmallImageFile=installer_icon.bmp
LicenseFile=license.txt
InfoBeforeFile=readme.txt
ChangesAssociations=no
DisableProgramGroupPage=auto
UninstallDisplayIcon={app}\icons\login.ico
UninstallDisplayName=Ream Management System

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startmenuicon"; Description: "Create a Start Menu shortcut"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; Optional: Include VC++ Redistributable in packages folder for offline installation
Source: "packages\vcredist_x64.exe"; DestDir: "{app}\packages"; Flags: ignoreversion skipifsourcedoesntexist
Source: "dist\ReamManagement.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: ".env"; DestDir: "{app}"; Flags: ignoreversion
Source: "config\*"; DestDir: "{app}\config"; Flags: ignoreversion recursesubdirs
Source: "database\*"; DestDir: "{app}\database"; Flags: ignoreversion recursesubdirs
Source: "gui\*"; DestDir: "{app}\gui"; Flags: ignoreversion recursesubdirs
Source: "icons\*"; DestDir: "{app}\icons"; Flags: ignoreversion recursesubdirs
Source: "logs\*"; DestDir: "{app}\logs"; Flags: ignoreversion recursesubdirs
Source: "modules\*"; DestDir: "{app}\modules"; Flags: ignoreversion recursesubdirs
Source: "requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "python-embed.zip"; DestDir: "{app}"; Flags: ignoreversion
Source: "packages\*"; DestDir: "{app}\python\Lib\site-packages"; Flags: ignoreversion recursesubdirs
Source: "post_install.bat"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Ream Management System"; Filename: "{app}\ReamManagement.exe"; IconFilename: "{app}\icons\login.ico"; Tasks: startmenuicon
Name: "{autodesktop}\Ream Management System"; Filename: "{app}\ReamManagement.exe"; IconFilename: "{app}\icons\login.ico"; Tasks: desktopicon
Name: "{group}\{cm:UninstallProgram,Ream Management System}"; Filename: "{uninstallexe}"; IconFilename: "{app}\icons\login.ico"; Tasks: startmenuicon

[Run]
Filename: "{app}\post_install.bat"; Description: "Setting up Python environment"; StatusMsg: "Configuring Python and dependencies..."; Flags: runhidden waituntilterminated
Filename: "{app}\ReamManagement.exe"; Description: "{cm:LaunchProgram,Ream Management System}"; StatusMsg: "Launching Ream Management System..."; Flags: nowait postinstall skipifsilent

[Dirs]
Name: "{app}\logs"; Permissions: everyone-modify
Name: "{app}\python\Lib\site-packages"; Permissions: everyone-modify

[Code]
procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpInstalling then
    WizardForm.StatusLabel.Caption := 'Installing Ream Management System...';
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  MsgBox('Welcome to the Ream Management System Setup Wizard!' + #13#10 +
         'This will install Ream Management System v1.0.0 on your computer.' + #13#10 +
         'Please close all other applications before continuing.', mbInformation, MB_OK);
end;
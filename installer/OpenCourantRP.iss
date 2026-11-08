; Inno Setup script. Build with:  python tools/build_installer.py
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

; /DTestBuild compiles a throwaway installer (own AppId, no compression) for automated checks.
#ifdef TestBuild
  #define AppGuid "{{7D0B6F0E-0000-4E39-9C1A-TESTTESTTEST}"
  #define Suffix "-test"
#else
  #define AppGuid "{{7D0B6F0E-3B7C-4E39-9C1A-0C0A6E5E4C11}"
  #define Suffix ""
#endif

[Setup]
AppId={#AppGuid}
AppName=OpenCourantRP
AppVersion={#AppVersion}
AppPublisher=Alejandro Ortiz-Bernardin
AppPublisherURL=https://camlab.cl/software/OpenCourantRP/
AppCopyright=Copyright 2026 Alejandro Ortiz-Bernardin
SetupIconFile=..\src\opencourantrp\resources\icon.ico
DefaultDirName={autopf}\OpenCourantRP
DefaultGroupName=OpenCourantRP
UninstallDisplayIcon={app}\OpenCourantRP.exe
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=OpenCourantRP-Setup-{#AppVersion}{#Suffix}
#ifdef TestBuild
Compression=none
#else
Compression=lzma2/normal
#endif
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern
DisableProgramGroupPage=yes

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "..\dist\OpenCourantRP\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\OpenCourantRP"; Filename: "{app}\OpenCourantRP.exe"; IconFilename: "{app}\OpenCourantRP.exe"
Name: "{group}\Uninstall OpenCourantRP"; Filename: "{uninstallexe}"
Name: "{autodesktop}\OpenCourantRP"; Filename: "{app}\OpenCourantRP.exe"; IconFilename: "{app}\OpenCourantRP.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\OpenCourantRP.exe"; Description: "Launch OpenCourantRP"; Flags: nowait postinstall skipifsilent

[Code]
// About text shown on the progress page while the files are being installed
// (keep in sync with src/opencourantrp/about.py)
procedure InitializeWizard;
var
  L: TNewStaticText;
begin
  L := TNewStaticText.Create(WizardForm);
  L.Parent := WizardForm.InstallingPage;
  L.AutoSize := False;
  L.WordWrap := True;
  L.Left := WizardForm.ProgressGauge.Left;
  L.Top := WizardForm.ProgressGauge.Top + WizardForm.ProgressGauge.Height + ScaleY(28);
  L.Width := WizardForm.ProgressGauge.Width;
  L.Height := ScaleY(120);
  L.Caption :=
    'OpenCourantRP' + #13#10 + #13#10 +
    'Run and Post-processor tool for the explicit finite element solver OpenCourant' + #13#10 + #13#10 +
    'License AGPL-3.0 or later' + #13#10 +
    'Copyright 2026 Alejandro Ortiz-Bernardin' + #13#10 +
    'https://camlab.cl/software/OpenCourantRP/';
end;

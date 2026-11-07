; Inno Setup script for YT-Downloader-Setup.exe (Windows).
; Built by .github/workflows/chrome-app-build.yml:
;   ISCC.exe /DAppVersion=1.1.0 /O<out> chrome-app\windows\installer.iss
; Installs for the current user only (no admin prompt) into
; %LOCALAPPDATA%\Programs\YT Downloader, registers the helper with Chrome and
; Edge, downloads yt-dlp/FFmpeg/Deno, and shows how to add the extension.

#define AppName "YT Downloader"
#define AppExe "YT Downloader.exe"
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6C3E8B1F-2A4D-4F7B-9E5C-8D1A0B2C3E4F}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=likelystudying
AppPublisherURL=https://github.com/likelystudying/yt_downloader
AppSupportURL=https://github.com/likelystudying/yt_downloader/blob/main/chrome-app/README.md
DefaultDirName={localappdata}\Programs\{#AppName}
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=YT-Downloader-Setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
; If Chrome is running the helper during an upgrade, offer to close it.
CloseApplications=yes
RestartApplications=no
SetupLogging=yes

[Files]
Source: "..\helper\dist\YT Downloader\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Upgrades: drop the previous version's runtime files first.
Type: filesandordirs; Name: "{app}\_internal"

[Run]
Filename: "{app}\{#AppExe}"; Parameters: "--register"; Flags: runhidden waituntilterminated; StatusMsg: "Connecting to Chrome and Edge…"
Filename: "{app}\{#AppExe}"; Parameters: "--install-tools"; Flags: runhidden waituntilterminated; StatusMsg: "Downloading yt-dlp, FFmpeg and Deno (usually about a minute)…"
Filename: "{app}\{#AppExe}"; Parameters: "--show-next-steps"; Description: "Show me how to add the extension to Chrome"; Flags: postinstall runhidden nowait skipifsilent

[UninstallRun]
; Removes the Chrome/Edge registration, the downloaded tools and the extension copy.
; Your downloaded videos are not touched.
Filename: "{app}\{#AppExe}"; Parameters: "--uninstall"; Flags: runhidden waituntilterminated; RunOnceId: "Unregister"

[Messages]
FinishedLabel=YT Downloader is installed.%n%nOne step left: add the extension to Chrome. Keep the box below ticked and click Finish to see how.

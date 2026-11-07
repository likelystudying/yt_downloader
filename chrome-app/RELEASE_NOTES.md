**YT Downloader for Chrome**: download YouTube videos (MP4) and audio (MP3) from Chrome, Edge or Brave,
with no Terminal or command prompt.

| Download | For |
|---|---|
| `YT-Downloader-Setup.exe` | Windows 10/11 (64-bit). Run it; if Windows says it protected your PC, click **More info → Run anyway**. |
| `YT-Downloader-mac.zip` | Apple Silicon Macs (M1 or newer), macOS 12+. Unzip, drag into Applications, open it (first time: System Settings → Privacy & Security → Open Anyway). |
| `yt-downloader_<version>_amd64.deb` | Ubuntu 22.04+ (64-bit). Double-click to install with App Center, then open “YT Downloader” from your apps once. Works with Chrome, Edge or Brave from `.deb` packages (not Snap Chromium). |

Then add the extension in `chrome://extensions` (Developer mode → Load unpacked). On Mac and Windows the
app copies the folder's location for you; on Ubuntu it's `/opt/yt-downloader/chrome-extension`. Full steps: [chrome-app/README.md](https://github.com/likelystudying/yt_downloader/blob/main/chrome-app/README.md).

**What's new**
- 1.2.0: Ubuntu version (`.deb`).
- 1.1.0: Windows version (per-user installer, works with Chrome and Edge).
- 1.0.1: Mac: fixes “Python.framework is damaged” when downloading.

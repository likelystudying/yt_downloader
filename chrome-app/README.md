# YT Downloader for Chrome (Mac and Windows)

Download a YouTube video as **MP4** or its audio as **MP3** from Chrome, straight into
`Downloads/YT Downloader`. No Terminal or command prompt needed.

It has two parts:

- **The Chrome extension** adds a toolbar button and a right-click menu on YouTube. It also works in
  Microsoft Edge and Brave.
- **The YT Downloader app** is a small helper that the browser starts in the background. It runs
  [yt-dlp](https://github.com/yt-dlp/yt-dlp), [FFmpeg](https://ffmpeg.org) and
  [Deno](https://deno.com) on your computer, so downloads come from your own internet connection.

```
Chrome extension ──native messaging──▶ YT Downloader app ──▶ yt-dlp + FFmpeg + Deno ──▶ Downloads/YT Downloader
```

Downloads are on the [Releases page](https://github.com/likelystudying/yt_downloader/releases):
`YT-Downloader-mac.zip` (Apple Silicon Macs, macOS 12+) and `YT-Downloader-Setup.exe` (Windows 10/11, 64-bit).

## Install on Windows (one time, about 3 minutes)

1. **Download** `YT-Downloader-Setup.exe`. If Chrome asks whether to keep it, choose **Keep**.
2. **Run it.** Windows may show “Windows protected your PC”, because the installer isn't signed with a
   paid certificate. Click **More info**, then **Run anyway**. No administrator password is needed.
3. The installer connects the helper to Chrome and Edge and downloads yt-dlp, FFmpeg and Deno
   (about 150 MB, usually a minute). Leave **“Show me how to add the extension to Chrome”** ticked and
   click **Finish**.
4. **Add the extension to Chrome:**
   1. In Chrome, go to `chrome://extensions`.
   2. Turn on **Developer mode** (top right).
   3. Click **Load unpacked**. Click the address bar at the top of the window that opens, press
      **Ctrl+V** (the installer already copied the folder's location), press **Enter**, then click
      **Select Folder**.
   4. Optional: click the puzzle-piece icon in Chrome's toolbar and pin **YT Downloader**.

   In Edge it's the same at `edge://extensions` (**Developer mode** is on the left).

## Install on Mac (one time, about 3 minutes)

1. **Download** `YT-Downloader-mac.zip` and double-click it to unzip.
2. **Drag “YT Downloader” into your Applications folder.** Do this before opening it.
3. **Open it** from Applications. The first time, macOS blocks it, because the app isn't signed with a
   paid Apple developer certificate:
   1. Click **Done** on the “Not Opened” message.
   2. Open **System Settings → Privacy & Security**, scroll down to **Security**, and click **Open Anyway**
      next to “YT Downloader”. Enter your password.
   3. Click **Open**.
4. The app registers itself with Chrome and downloads yt-dlp, FFmpeg and Deno (over 100 MB, usually
   about a minute). A message then shows the last step.
5. **Add the extension to Chrome:**
   1. In Chrome, go to `chrome://extensions`.
   2. Turn on **Developer mode** (top right).
   3. Click **Load unpacked**. Press **⌘⇧G**, paste with **⌘V** (the app already copied the folder's
      location), press **Return**, then click **Select**.
   4. Optional: click the puzzle-piece icon in Chrome's toolbar and pin **YT Downloader**.

The extension isn't in the Chrome Web Store because the store doesn't accept YouTube downloaders, so
it's loaded this way instead. Chrome may show a notice about developer-mode extensions; that's expected.

## Use

- On a YouTube video page, click the **YT Downloader** toolbar button, then **Video (MP4)** or **Audio (MP3)**.
- Or **right-click** the video page, or any YouTube video link on any site, and choose a download.
- Progress shows in the popup and on the toolbar button. You get a notification when a file is ready;
  click it to show the file in Finder or File Explorer.
- Downloads run one at a time. You can queue several and cancel any of them.
- To save somewhere else, click **Change** at the bottom of the popup.

Videos are saved as H.264/AAC MP4, which plays everywhere (QuickTime, Photos, the Windows Media Player
and Photos apps). A link that is part of a playlist downloads just that one video.

## Keeping it working

YouTube changes often and old yt-dlp versions stop working. The helper updates yt-dlp by itself every
few days. If downloads start failing, click **Update yt-dlp** in the popup and try again.

To install a newer version of the helper:

- **Windows:** run the new `YT-Downloader-Setup.exe`; it upgrades in place.
- **Mac:** download the new zip, replace the app in Applications, and open it once.

Then click the reload arrow on YT Downloader in `chrome://extensions`.

## Troubleshooting

| What you see | What to do |
|---|---|
| Popup says “Install the helper app” although you did | **Windows:** run the installer again. **Mac:** open YT Downloader from Applications again (it must be in Applications). |
| “YouTube asked to confirm you're not a bot” | Too many requests in a short time. Wait a while and try again. |
| “Requested format is not available” or other new errors | Click **Update yt-dlp**, then download again. |
| Mac: “Move YT Downloader to your Applications folder first” | You opened it from Downloads or the zip. Drag it to Applications, then open it from there. |
| Mac: “Python.framework is damaged and can't be opened” when you download | Fixed in 1.0.1. Install the current version, open it once, then click **Update yt-dlp**. |
| Mac: asked whether Chrome or YT Downloader may access your Downloads folder | Click **Allow**. |
| Windows: antivirus warns about YT Downloader or yt-dlp | Some antivirus tools flag unsigned Python-based programs. The files are built from this repository by GitHub Actions. |
| Anything else | Send the log: **Mac** `~/Library/Application Support/YT Downloader/helper.log` (Finder → Go → Go to Folder…), **Windows** `%LOCALAPPDATA%\YT Downloader\helper.log` (paste into File Explorer's address bar). |

## Uninstall

**Windows:** Settings → Apps → Installed apps → **YT Downloader** → Uninstall. This removes the app, its
tools and the Chrome/Edge registration. Then click **Remove** on YT Downloader in `chrome://extensions`.

**Mac:**
1. In `chrome://extensions`, click **Remove** on YT Downloader.
2. Drag **YT Downloader** from Applications to the Trash.
3. In Finder, choose **Go → Go to Folder…** and delete:
   - `~/Library/Application Support/YT Downloader`
   - `~/Library/Application Support/Google/Chrome/NativeMessagingHosts/com.likelystudying.ytdownloader.json`

Your downloaded files are never touched.

## Where things live

| What | Mac | Windows |
|---|---|---|
| The app | `/Applications/YT Downloader.app` | `%LOCALAPPDATA%\Programs\YT Downloader` |
| yt-dlp, FFmpeg, FFprobe, Deno | `~/Library/Application Support/YT Downloader/bin` | `%LOCALAPPDATA%\YT Downloader\bin` |
| Extension files (loaded unpacked) | `~/Library/Application Support/YT Downloader/Chrome Extension` | `%LOCALAPPDATA%\YT Downloader\Chrome Extension` |
| Settings and log | same folder: `config.json`, `helper.log` | same folder: `config.json`, `helper.log` |
| Browser registration | `~/Library/Application Support/Google/Chrome/NativeMessagingHosts/…json` | registry `HKCU\Software\Google\Chrome\NativeMessagingHosts\com.likelystudying.ytdownloader` (also Edge) |
| Downloads | `~/Downloads/YT Downloader` (changeable) | `Downloads\YT Downloader` (changeable) |

Brave, Chromium (both) and Chrome Beta/Dev/Canary (Mac) are registered too if they're installed.

## For developers

```
chrome-app/
├── chrome-extension/      Manifest V3 extension (popup, right-click menu, background worker)
├── helper/
│   ├── ytdl_helper.py     The helper: native messaging host + installer (Python stdlib + certifi)
│   ├── YTDownloader.spec  PyInstaller spec (Mac .app / Windows .exe)
│   └── tests/             pytest suite + e2e_chrome.py (real Chrome, extension and helper)
├── windows/installer.iss  Inno Setup script for YT-Downloader-Setup.exe
├── ci/                    protocol_check.py (talks to the built app like Chrome does),
│                          e2e_chromium.py (real Chromium + extension + built/installed app)
├── assets/                icon-1024.png and icon.ico (tools/make_icons.py draws them)
└── README.md
```

- The extension has a fixed ID (`dchdeelhpdnkdichogpodkgkhojfehph`, from the `key` in its manifest).
  The helper accepts only that ID.
- `.github/workflows/chrome-app-build.yml` builds both apps. Each job downloads the real tools, runs a
  video and an audio download through the built app the way Chrome does, and drives real Chromium with
  the extension. The Windows job also installs and uninstalls silently and checks the registry.
- To publish a release: **Actions → Chrome helper apps (Mac + Windows) → Run workflow → Publish a release**.
- Tests: `pip install yt-dlp pytest` and FFmpeg, then `python -m pytest chrome-app/helper/tests`.
  End-to-end in Chrome for Testing: `python chrome-app/helper/tests/e2e_chrome.py`.

Only download content you have the right to download, and follow YouTube's Terms of Service.

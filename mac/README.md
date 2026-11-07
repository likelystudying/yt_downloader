# YT Downloader for Mac (Chrome extension)

Download a YouTube video as **MP4** or its audio as **MP3** from Chrome, straight into
`~/Downloads/YT Downloader`. You never need Terminal.

It has two parts:

- **The Chrome extension** adds a toolbar button and a right-click menu on YouTube.
- **The YT Downloader app** is a small helper that Chrome starts in the background. It runs
  [yt-dlp](https://github.com/yt-dlp/yt-dlp), [FFmpeg](https://ffmpeg.org) and
  [Deno](https://deno.com) on your Mac, so downloads come from your own internet connection.

```
Chrome extension ──native messaging──▶ YT Downloader.app ──▶ yt-dlp + FFmpeg + Deno ──▶ ~/Downloads/YT Downloader
```

## Install (one time, about 3 minutes)

1. **Download** `YT-Downloader-mac.zip` from the
   [Releases page](https://github.com/likelystudying/yt_downloader/releases) and double-click it to unzip.
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
it's loaded this way instead.

## Use

- On a YouTube video page, click the **YT Downloader** toolbar button, then **Video (MP4)** or **Audio (MP3)**.
- Or **right-click** the video page, or any YouTube video link on any site, and choose a download.
- Progress shows in the popup and on the toolbar button. You get a notification when a file is ready;
  click it to show the file in Finder.
- Downloads run one at a time. You can queue several and cancel any of them.
- To save somewhere else, click **Change** at the bottom of the popup.

Videos are saved as H.264/AAC MP4, which plays in QuickTime, Photos and iMovie. A link that is part of a
playlist downloads just that one video.

## Keeping it working

YouTube changes often and old yt-dlp versions stop working. The helper updates yt-dlp by itself every
few days. If downloads start failing, click **Update yt-dlp** in the popup and try again.

To install a newer version of the helper, download the new zip, replace the app in Applications, open it
once, then click the reload arrow on YT Downloader in `chrome://extensions`.

## Troubleshooting

| What you see | What to do |
|---|---|
| Popup says “Install the helper app” although you did | Open YT Downloader from Applications again. It re-registers with Chrome. Make sure it was in Applications when you opened it. |
| “Move YT Downloader to your Applications folder first” | You opened it from Downloads or the zip. Drag it to Applications, then open it from there. |
| “YouTube asked to confirm you're not a bot” | Too many requests in a short time. Wait a while and try again. |
| “Requested format is not available” or other new errors | Click **Update yt-dlp**, then download again. |
| macOS asks whether Chrome or YT Downloader may access your Downloads folder | Click **Allow**. |
| Anything else | The log is at `~/Library/Application Support/YT Downloader/helper.log` (Finder → Go → Go to Folder…). |

## Uninstall

1. In `chrome://extensions`, click **Remove** on YT Downloader.
2. Drag **YT Downloader** from Applications to the Trash.
3. In Finder, choose **Go → Go to Folder…** and delete:
   - `~/Library/Application Support/YT Downloader`
   - `~/Library/Application Support/Google/Chrome/NativeMessagingHosts/com.likelystudying.ytdownloader.json`

Your downloaded files are not touched.

## Where things live

| What | Where |
|---|---|
| The app | `/Applications/YT Downloader.app` |
| yt-dlp, FFmpeg, FFprobe, Deno | `~/Library/Application Support/YT Downloader/bin` |
| Extension files (loaded unpacked) | `~/Library/Application Support/YT Downloader/Chrome Extension` |
| Settings and log | `~/Library/Application Support/YT Downloader/config.json`, `helper.log` |
| Chrome registration | `~/Library/Application Support/Google/Chrome/NativeMessagingHosts/com.likelystudying.ytdownloader.json` |
| Downloads | `~/Downloads/YT Downloader` (changeable) |

Brave, Edge, Chromium and Chrome Beta/Dev/Canary are registered too if they're installed.

## For developers

```
mac/
├── chrome-extension/   Manifest V3 extension (popup, right-click menu, background worker)
├── helper/
│   ├── ytdl_helper.py  The helper: native messaging host + installer (Python stdlib + certifi)
│   ├── YTDownloader.spec  PyInstaller spec for “YT Downloader.app”
│   └── tests/          pytest suite + e2e_chrome.py (real Chrome, extension and helper)
├── ci/protocol_check.py  Talks to the built app like Chrome does (used by the workflow)
├── assets/icon-1024.png  App icon source (tools/make_icons.py draws it)
└── README.md
```

- The extension has a fixed ID (`dchdeelhpdnkdichogpodkgkhojfehph`, from the `key` in its manifest).
  The helper accepts only that ID.
- The app is built by `.github/workflows/mac-build.yml` on a macOS runner. That workflow also downloads
  the real tools and runs a video and an audio download through the built app. To publish a release:
  **Actions → Mac app (Chrome helper) → Run workflow → Publish a release**.
- Tests: `pip install yt-dlp pytest` and FFmpeg, then `python -m pytest mac/helper/tests`.
  End-to-end in Chrome for Testing: `python mac/helper/tests/e2e_chrome.py`.

Only download content you have the right to download, and follow YouTube's Terms of Service.

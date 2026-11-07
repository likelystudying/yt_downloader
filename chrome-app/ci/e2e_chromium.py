"""Drive real Chromium + the extension against a built or installed helper.

    python chrome-app/ci/e2e_chromium.py "<helper executable>"

Used by the macOS and Windows build jobs, where this is the only way to check
that the browser itself can start the helper (on Windows Chrome goes through
cmd.exe; on macOS files the helper writes get Chrome's quarantine flag).

Needs the helper's tools already installed (YTDL_HOME, or the default folder),
FFmpeg among them, and `python -m playwright install chromium`.
YouTube isn't contacted: the extension gets a real YouTube link, and the
helper's YTDL_URL_OVERRIDE test switch points yt-dlp at a local clip.
"""
from __future__ import annotations

import functools
import http.server
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "helper"))
import ytdl_helper as h  # noqa: E402  (same paths as the helper, from YTDL_HOME)

VIDEO_URL = "https://www.youtube.com/watch?v=e2eTEST0001"
SHOTS = Path(os.environ.get("E2E_SHOTS", tempfile.gettempdir()))



class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def main(helper_exe: str) -> None:
    work = Path(tempfile.mkdtemp(prefix="ytdl-e2e-"))
    profile, downloads, media = work / "profile", work / "Downloads", work / "media"
    media.mkdir(parents=True)
    subprocess.run([str(h.tool_path("ffmpeg")), "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc=size=640x360:rate=25", "-f", "lavfi", "-i", "sine=frequency=330",
                    "-t", "6", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(media / "clip.mp4")],
                   check=True)
    handler = functools.partial(QuietHandler, directory=str(media))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    clip_url = f"http://127.0.0.1:{server.server_address[1]}/clip.mp4"

    # Register the helper so Chromium (not just Chrome) finds it.
    if h.IS_WIN:
        subprocess.run([helper_exe, "--register"], check=True)
        h.set_registry_default(rf"Software\Chromium\NativeMessagingHosts\{h.HOST_NAME}",
                               str(h.SUPPORT_DIR / "native-messaging-host.json"))
    else:
        dirs = [profile / "NativeMessagingHosts",
                Path.home() / "Library" / "Application Support" / "Chromium" / "NativeMessagingHosts"]
        subprocess.run([helper_exe, "--register"], check=True,
                       env={**os.environ, "YTDL_NM_DIRS": os.pathsep.join(map(str, dirs))})
    ext_dir = h.EXTENSION_DIR
    assert (ext_dir / "manifest.json").exists(), ext_dir

    env = {**os.environ, "YTDL_URL_OVERRIDE": clip_url, "YTDL_DOWNLOADS": str(downloads), "YTDL_NO_OPEN": "1"}
    with sync_playwright() as p:
        browser = ({"executable_path": os.environ["E2E_CHROME_PATH"]} if os.environ.get("E2E_CHROME_PATH")
                   else {"channel": "chromium"})  # local runs can point at Chrome for Testing
        ctx = p.chromium.launch_persistent_context(
            str(profile), headless=True, env=env, **browser,
            args=[f"--disable-extensions-except={ext_dir}", f"--load-extension={ext_dir}"],
            viewport={"width": 380, "height": 640})
        try:
            sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker", timeout=30000)
            assert h.EXTENSION_ID in sw.url, f"unexpected extension id: {sw.url}"
            page = ctx.new_page()
            page.goto(f"chrome-extension://{h.EXTENSION_ID}/popup.html")
            page.wait_for_selector("#versions:has-text('yt-dlp 2')", timeout=60000)
            print("popup footer:", page.inner_text("#versions"))
            page.fill("#url", VIDEO_URL)
            page.click("#btn-video")
            page.wait_for_selector("li.job.done", timeout=180000)
            page.click("#btn-audio")
            page.locator("li.job.done").nth(1).wait_for(timeout=180000)
            page.screenshot(path=str(SHOTS / f"e2e-{sys.platform}.png"))
            print("jobs:", page.locator("li.job .job-meta").all_inner_texts())
            assert page.locator("li.job.error").count() == 0
        except Exception:
            for pg in ctx.pages:
                try:
                    pg.screenshot(path=str(SHOTS / f"e2e-{sys.platform}-failed.png"))
                    print("popup text at failure:\n", pg.inner_text("body"))
                except Exception:
                    pass
            raise
        finally:
            ctx.close()

    files = sorted(p.name for p in downloads.iterdir())
    print("files:", files)
    assert files == ["clip [clip].mp3", "clip [clip].mp4"], files
    print("CHROMIUM E2E PASSED")


if __name__ == "__main__":
    main(sys.argv[1])

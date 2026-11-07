"""End-to-end check in a real Chrome: extension + native messaging + helper.

    python3 mac/helper/tests/e2e_chrome.py [path-to-chrome]

Runs on Linux with Chrome for Testing (branded Chrome ignores --load-extension).
YouTube isn't contacted: the test's yt-dlp wrapper swaps the YouTube URL for a
clip served from a local HTTP server, so the extension still sees real
YouTube links while yt-dlp, FFmpeg and the helper all run for real.
"""
from __future__ import annotations

import functools
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
MAC = HERE.parents[1]
HELPER = MAC / "helper" / "ytdl_helper.py"
EXT_ID = "dchdeelhpdnkdichogpodkgkhojfehph"
CHROME = sys.argv[1] if len(sys.argv) > 1 else shutil.which("google-chrome") or "google-chrome"
VIDEO_URL = "https://www.youtube.com/watch?v=e2eTEST0001"
SHOTS = Path(os.environ.get("E2E_SHOTS", tempfile.gettempdir()))


def make_clip(root: Path) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc=size=640x360:rate=25", "-f", "lavfi", "-i", "sine=frequency=330", "-t", "8",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(root / "clip.mp4")], check=True)


def serve(root: Path) -> str:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}/clip.mp4"


def fake_ytdlp(bin_dir: Path, local_url: str) -> None:
    script = bin_dir / "yt-dlp"
    script.write_text(f"""#!{sys.executable}
import sys, runpy
args = sys.argv[1:]
if "--" in args:
    args = args[:args.index("--") + 1] + ["{local_url}"]
sys.argv = ["yt-dlp"] + args
runpy.run_module("yt_dlp", run_name="__main__")
""")
    script.chmod(0o755)
    (bin_dir / "deno").write_text('#!/bin/sh\necho "deno 2.5.6"\n')
    (bin_dir / "deno").chmod(0o755)
    for name in ("ffmpeg", "ffprobe"):
        (bin_dir / name).symlink_to(shutil.which(name))


def run(register: bool) -> dict:
    work = Path(tempfile.mkdtemp(prefix="ytdl-e2e-"))
    profile, support, downloads = work / "profile", work / "support", work / "Downloads"
    (support / "bin").mkdir(parents=True)
    media = work / "media"
    media.mkdir()
    make_clip(media)
    fake_ytdlp(support / "bin", serve(media))

    env = {**os.environ, "YTDL_HOME": str(support), "YTDL_DOWNLOADS": str(downloads), "YTDL_NO_OPEN": "1",
           "YTDL_NM_DIRS": str(profile / "NativeMessagingHosts")}
    if register:
        subprocess.run([sys.executable, str(HELPER), "--register"], env=env, check=True, capture_output=True)
    ext_dir = support / "Chrome Extension" if register else MAC / "chrome-extension"

    results: dict = {"downloads": downloads}
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(profile), executable_path=CHROME, headless=True, env=env,
            args=[f"--disable-extensions-except={ext_dir}", f"--load-extension={ext_dir}"],
            viewport={"width": 380, "height": 640})
        sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker", timeout=20000)
        assert EXT_ID in sw.url, f"unexpected extension id: {sw.url}"
        page = ctx.new_page()
        page.goto(f"chrome-extension://{EXT_ID}/popup.html")

        if not register:
            page.wait_for_selector("text=Install the helper app", timeout=20000)
            page.screenshot(path=str(SHOTS / "popup-missing.png"))
            results["missing_banner"] = True
            ctx.close()
            return results

        page.wait_for_selector("#versions:has-text('yt-dlp')", timeout=30000)
        assert page.is_disabled("#btn-video"), "buttons must start disabled without a link"
        page.fill("#url", "https://vimeo.com/12345")
        assert page.is_disabled("#btn-video")
        assert "isn't a single YouTube video" in page.inner_text("#url-hint")
        page.fill("#url", VIDEO_URL)
        page.click("#btn-video")
        page.wait_for_selector("li.job.done", timeout=90000)
        page.click("#btn-audio")
        page.locator("li.job.done").nth(1).wait_for(timeout=90000)
        page.screenshot(path=str(SHOTS / "popup-done.png"))
        results["titles"] = page.locator("li.job .job-title").all_inner_texts()
        results["meta"] = page.locator("li.job .job-meta").all_inner_texts()
        results["versions"] = page.inner_text("#versions")
        results["folder"] = page.inner_text("#folder")
        stored = sw.evaluate("chrome.storage.local.get(['jobs','helper'])")
        results["helper_state"] = stored["helper"]["state"]
        results["badge"] = sw.evaluate("chrome.action.getBadgeText({})")
        page.click("text=Clear finished")
        page.wait_for_selector("#empty:not([hidden])", timeout=5000)
        ctx.close()
    results["files"] = sorted(p.name for p in downloads.iterdir())
    return results


if __name__ == "__main__":
    missing = run(register=False)
    print("helper missing ->", json.dumps({k: v for k, v in missing.items() if k != "downloads"}))
    ok = run(register=True)
    print("helper installed ->", json.dumps({k: str(v) if isinstance(v, Path) else v for k, v in ok.items()},
                                            ensure_ascii=False, indent=1))
    assert ok["files"] == ["clip [clip].mp3", "clip [clip].mp4"], ok["files"]
    print("E2E PASSED")

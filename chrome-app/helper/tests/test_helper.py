"""Tests for the YT Downloader helper.

The integration tests start the helper the way Chrome does (first argument
chrome-extension://<id>/, length-prefixed JSON on stdin/stdout) and download
from a local HTTP server, so no YouTube access is needed. They need yt-dlp
(Python package) and ffmpeg/ffprobe on PATH.
"""
from __future__ import annotations

import http.server
import json
import os
import shutil
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import quote

import pytest

HERE = Path(__file__).resolve().parent
HELPER = HERE.parent / "ytdl_helper.py"
sys.path.insert(0, str(HERE.parent))
import ytdl_helper as h  # noqa: E402

ORIGIN = f"chrome-extension://{h.EXTENSION_ID}/"
HAVE_TOOLS = all(shutil.which(t) for t in ("ffmpeg", "ffprobe"))
try:
    import yt_dlp  # noqa: F401
except ImportError:
    HAVE_TOOLS = False
needs_tools = pytest.mark.skipif(not HAVE_TOOLS, reason="needs yt-dlp, ffmpeg and ffprobe")


# --------------------------------------------------------------------------
# Unit tests
# --------------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtube.com/watch?v=dQw4w9WgXcQ&list=PL123&index=2",
    "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ?t=10",
    "https://www.youtube.com/shorts/abcdefghijk",
    "https://www.youtube.com/live/abcdefghijk",
])
def test_valid_urls(url, monkeypatch):
    monkeypatch.setattr(h, "ALLOW_ANY_URL", False)
    assert h.validate_url(url) is None


@pytest.mark.parametrize("url", [
    "", "not a url", "ftp://youtube.com/watch?v=dQw4w9WgXcQ",
    "https://www.youtube.com/", "https://www.youtube.com/@somechannel",
    "https://www.youtube.com/playlist?list=PL123", "https://vimeo.com/123456",
    "https://evil.example/watch?v=dQw4w9WgXcQ", "https://youtube.com.evil.example/watch?v=dQw4w9WgXcQ",
])
def test_invalid_urls(url, monkeypatch):
    monkeypatch.setattr(h, "ALLOW_ANY_URL", False)
    assert h.validate_url(url)


def test_command_keeps_downloads_out_of_playlists_and_uses_presets(tmp_path, monkeypatch):
    monkeypatch.setattr(h, "BIN_DIR", tmp_path)
    for name in ("yt-dlp", "ffmpeg", "deno"):
        (tmp_path / h.tool_layout()[name]).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / h.tool_layout()[name]).touch()
    video = h.build_command("https://youtu.be/dQw4w9WgXcQ", "video", tmp_path / "w")
    audio = h.build_command("https://youtu.be/dQw4w9WgXcQ", "audio", tmp_path / "w")
    assert "--no-playlist" in video and "--ignore-config" in video
    assert video[video.index("-t") + 1] == "mp4" and audio[audio.index("-t") + 1] == "mp3"
    assert video[video.index("--js-runtimes") + 1] == f"deno:{tmp_path / 'deno'}"
    assert video[video.index("-P") + 1] == str(tmp_path / "w")
    assert video[-2:] == ["--", "https://youtu.be/dQw4w9WgXcQ"]  # URL can't be read as an option


def test_progress_counts_video_and_audio_streams():
    host = h.Host.__new__(h.Host)
    host.send = lambda message: None
    job = {"mode": "video", "part": 0, "percent": None}
    host._on_progress(job, "500|1000|NA|2000|3")
    assert (job["part"], job["percent"], job["phase"]) == (1, 50.0, "Downloading video")
    host._on_progress(job, "1000|1000|NA|2000|0")
    host._on_progress(job, "100|NA|1000|2000|5")  # second stream starts
    assert (job["part"], job["percent"], job["phase"]) == (2, 10.0, "Downloading audio")


def test_friendly_errors_for_blocked_ytdlp():
    message = h.friendly_error("[PYI-57784:ERROR] Failed to load Python shared library '/var/folders/x/Python': "
                               "dlopen(...): code signature ... library load disallowed by system")
    assert "Update yt-dlp" in message and "PYI" not in message


def test_friendly_errors():
    assert "not a bot" in h.friendly_error("Sign in to confirm you’re not a bot. This helps protect our community")
    assert "Update yt-dlp" in h.friendly_error("[youtube] abc: Requested format is not available")
    assert h.friendly_error("") == "Download failed."


def test_register_writes_manifest_and_copies_extension(tmp_path):
    env = {**os.environ, "YTDL_HOME": str(tmp_path / "home"),
           "YTDL_NM_DIRS": os.pathsep.join([str(tmp_path / "chrome"), str(tmp_path / "brave")])}
    subprocess.run([sys.executable, str(HELPER), "--register"], env=env, check=True, capture_output=True)
    for browser in ("chrome", "brave"):
        manifest = json.loads((tmp_path / browser / f"{h.HOST_NAME}.json").read_text())
        assert manifest["allowed_origins"] == [ORIGIN]
        assert manifest["type"] == "stdio"
        assert os.access(manifest["path"], os.X_OK)
    ext = json.loads((tmp_path / "home" / "Chrome Extension" / "manifest.json").read_text())
    assert ext["manifest_version"] == 3


def test_extension_key_matches_host_extension_id():
    import base64
    import hashlib
    manifest = json.loads((HERE.parent.parent / "chrome-extension" / "manifest.json").read_text())
    digest = hashlib.sha256(base64.b64decode(manifest["key"])).hexdigest()[:32]
    assert "".join(chr(ord("a") + int(c, 16)) for c in digest) == h.EXTENSION_ID


def test_wrong_caller_is_refused(tmp_path):
    result = subprocess.run([sys.executable, str(HELPER), "chrome-extension://someoneelse/"],
                            env={**os.environ, "YTDL_HOME": str(tmp_path)}, input=b"", capture_output=True)
    assert result.returncode == 1


# --------------------------------------------------------------------------
# Integration tests: real yt-dlp + ffmpeg, local media server
# --------------------------------------------------------------------------

class SlowHandler(http.server.SimpleHTTPRequestHandler):
    """Serves files; anything under /slow/ trickles out so it can be cancelled."""

    def log_message(self, *args):
        pass

    def copyfile(self, source, outputfile):
        if not self.path.startswith("/slow/"):
            return super().copyfile(source, outputfile)
        while chunk := source.read(4096):
            outputfile.write(chunk)
            time.sleep(0.05)

    def translate_path(self, path):
        return super().translate_path(path.replace("/slow/", "/", 1))


@pytest.fixture(scope="module")
def media_server(tmp_path_factory):
    root = tmp_path_factory.mktemp("media")
    for name in ("sample clip.mp4", "テスト動画.mp4"):
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25", "-f", "lavfi", "-i", "sine=frequency=440",
                        "-t", "4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(root / name)],
                       check=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc=size=640x480:rate=25", "-t", "30", "-c:v", "libx264", "-b:v", "2M",
                    str(root / "big.mp4")], check=True)
    handler = lambda *a, **k: SlowHandler(*a, directory=str(root), **k)  # noqa: E731
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


class Chrome:
    """Plays Chrome's side of native messaging."""

    def __init__(self, tmp_path: Path):
        self.home = tmp_path / "support"
        self.downloads = tmp_path / "Downloads"
        bin_dir = self.home / "bin"
        bin_dir.mkdir(parents=True)
        ytdlp = bin_dir / h.tool_layout()["yt-dlp"]
        ytdlp.parent.mkdir(parents=True)
        ytdlp.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m yt_dlp "$@"\n')
        (bin_dir / "deno").write_text('#!/bin/sh\necho "deno 2.5.6 (stable, release, aarch64-apple-darwin)"\n')
        for path in (ytdlp, bin_dir / "deno"):
            path.chmod(0o755)
        for name in ("ffmpeg", "ffprobe"):
            (bin_dir / name).symlink_to(shutil.which(name))
        env = {k: v for k, v in os.environ.items() if k not in ("LANG", "LC_ALL", "LC_CTYPE", "PYTHONIOENCODING")}
        env.update(YTDL_HOME=str(self.home), YTDL_DOWNLOADS=str(self.downloads),
                   YTDL_ALLOW_ANY_URL="1", YTDL_NO_OPEN="1", PYTHONPATH="")
        self.proc = subprocess.Popen([sys.executable, str(HELPER), ORIGIN], env=env,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.messages: list[dict] = []
        self.lock = threading.Condition()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        out = self.proc.stdout
        while header := out.read(4):
            (length,) = struct.unpack("=I", header)
            message = json.loads(out.read(length))
            with self.lock:
                self.messages.append(message)
                self.lock.notify_all()

    def send(self, message: dict):
        data = json.dumps(message).encode()
        self.proc.stdin.write(struct.pack("=I", len(data)) + data)
        self.proc.stdin.flush()

    def wait_for(self, predicate, timeout=60.0) -> dict:
        deadline = time.monotonic() + timeout
        seen = 0
        with self.lock:
            while True:
                for message in self.messages[seen:]:
                    if predicate(message):
                        return message
                seen = len(self.messages)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AssertionError(f"timed out; last messages: {self.messages[-5:]}")
                self.lock.wait(remaining)

    def wait_job(self, job_id, statuses=("done", "error", "cancelled"), timeout=90.0) -> dict:
        return self.wait_for(lambda m: m.get("type") == "job" and m["job"]["id"] == job_id
                             and m["job"]["status"] in statuses, timeout)["job"]

    def close(self):
        if self.proc.poll() is None:
            self.proc.stdin.close()
            self.proc.wait(timeout=20)


@pytest.fixture
def chrome(tmp_path):
    c = Chrome(tmp_path)
    yield c
    c.close()


@needs_tools
def test_hello_reports_tools(chrome):
    chrome.send({"type": "hello"})
    hello = chrome.wait_for(lambda m: m["type"] == "hello")
    assert hello["missing"] == []
    assert hello["tools"]["deno"] == "2.5.6"
    assert hello["tools"]["yt-dlp"]
    assert hello["downloadDir"] == str(chrome.downloads)


@needs_tools
def test_video_then_audio_keeps_both_files(chrome, media_server):
    url = f"{media_server}/{quote('sample clip.mp4')}"
    chrome.send({"type": "download", "id": "v1", "url": url, "mode": "video", "title": "from tab"})
    video = chrome.wait_job("v1")
    assert video["status"] == "done", video
    chrome.send({"type": "download", "id": "a1", "url": url, "mode": "audio"})
    audio = chrome.wait_job("a1")
    assert audio["status"] == "done", audio
    assert video["title"] == "sample clip"  # yt-dlp's title replaces the tab title
    files = sorted(p.name for p in chrome.downloads.iterdir())
    assert files == ["sample clip [sample clip].mp3", "sample clip [sample clip].mp4"]  # regression: mp4 survived
    assert Path(audio["file"]) == chrome.downloads / "sample clip [sample clip].mp3"
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name", "-of", "csv=p=0",
                            video["file"]], capture_output=True, text=True).stdout.split()
    assert probe == ["h264", "aac"]
    assert list((chrome.home / "work").iterdir()) == []  # scratch folders cleaned up


@needs_tools
def test_japanese_title_without_utf8_locale(chrome, media_server):
    chrome.send({"type": "download", "id": "jp", "url": f"{media_server}/{quote('テスト動画.mp4')}", "mode": "audio"})
    job = chrome.wait_job("jp")
    assert job["status"] == "done", job
    assert job["title"] == "テスト動画"
    assert (chrome.downloads / "テスト動画 [テスト動画].mp3").exists()


@needs_tools
def test_progress_messages_arrive(chrome, media_server):
    chrome.send({"type": "download", "id": "p1", "url": f"{media_server}/slow/big.mp4", "mode": "video"})
    running = chrome.wait_for(lambda m: m["type"] == "job" and m["job"]["id"] == "p1"
                              and m["job"]["status"] == "running" and m["job"]["percent"])
    assert 0 < running["job"]["percent"] < 100
    chrome.send({"type": "cancel", "id": "p1"})
    assert chrome.wait_job("p1")["status"] == "cancelled"


@needs_tools
def test_cancel_running_and_queued_jobs(chrome, media_server):
    slow = f"{media_server}/slow/big.mp4"
    chrome.send({"type": "download", "id": "c1", "url": slow, "mode": "video"})
    chrome.send({"type": "download", "id": "c2", "url": slow, "mode": "audio"})
    chrome.wait_for(lambda m: m["type"] == "job" and m["job"]["id"] == "c1" and m["job"]["percent"])
    chrome.send({"type": "cancel", "id": "c2"})
    assert chrome.wait_job("c2")["status"] == "cancelled"
    chrome.send({"type": "cancel", "id": "c1"})
    assert chrome.wait_job("c1")["status"] == "cancelled"
    assert not chrome.downloads.exists() or list(chrome.downloads.iterdir()) == []
    time.sleep(0.5)
    assert list((chrome.home / "work").iterdir()) == []


@needs_tools
def test_bad_requests_are_reported_not_fatal(chrome, media_server):
    chrome.send({"type": "download", "id": "b1", "url": "javascript:alert(1)", "mode": "video"})
    assert chrome.wait_job("b1")["status"] == "error"
    chrome.send({"type": "download", "id": "b2", "url": f"{media_server}/missing.mp4", "mode": "video"})
    failed = chrome.wait_job("b2")
    assert failed["status"] == "error" and failed["error"]
    chrome.send({"type": "nonsense"})
    chrome.wait_for(lambda m: m["type"] == "error")
    chrome.send({"type": "ping"})
    chrome.wait_for(lambda m: m["type"] == "pong")


@needs_tools
def test_chrome_closing_stops_helper_and_download(chrome, media_server):
    chrome.send({"type": "download", "id": "q1", "url": f"{media_server}/slow/big.mp4", "mode": "video"})
    chrome.wait_for(lambda m: m["type"] == "job" and m["job"]["id"] == "q1" and m["job"]["percent"])
    chrome.proc.stdin.close()
    assert chrome.proc.wait(timeout=20) == 0
    time.sleep(0.5)
    leftovers = subprocess.run(["pgrep", "-f", "slow/big.mp4"], capture_output=True, text=True).stdout.split()
    assert leftovers == []


# --------------------------------------------------------------------------
# Tool installation (yt-dlp ships as a folder; 1.0.0's single file is replaced)
# --------------------------------------------------------------------------

def _fake_ytdlp_zip(path: Path, version: str) -> Path:
    import zipfile
    with zipfile.ZipFile(path, "w") as zf:
        info = zipfile.ZipInfo(Path(h.tool_layout()["yt-dlp"]).name)
        info.external_attr = (0o100755 << 16)
        zf.writestr(info, f"#!/bin/sh\necho {version}\n")
        zf.writestr("_internal/base_library.zip", b"stub")
        lib = zipfile.ZipInfo("_internal/Python")
        lib.external_attr = (0o100755 << 16)
        zf.writestr(lib, b"stub")
    return path


@pytest.fixture
def tool_server(tmp_path):
    root = tmp_path / "srv"
    root.mkdir()
    handler = lambda *a, **k: SlowHandler(*a, directory=str(root), **k)  # noqa: E731
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield root, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    home = tmp_path / "support"
    for name, value in {"SUPPORT_DIR": home, "BIN_DIR": home / "bin", "CONFIG_FILE": home / "config.json",
                        "LOG_FILE": home / "helper.log"}.items():
        monkeypatch.setattr(h, name, value)
    return home


def test_install_ytdlp_folder_replaces_single_file_build(isolated, tool_server, monkeypatch):
    root, base = tool_server
    _fake_ytdlp_zip(root / "yt-dlp_macos.zip", "2026.11.01")
    monkeypatch.setattr(h, "tool_specs", lambda: {"yt-dlp": {"url": f"{base}/yt-dlp_macos.zip", "folder": "yt-dlp"}})
    h.BIN_DIR.mkdir(parents=True)
    (h.BIN_DIR / "yt-dlp").write_text("old single-file build")   # what 1.0.0 installed
    h.prepare_tools()
    assert not (h.BIN_DIR / "yt-dlp").exists()
    h.install_tool("yt-dlp")
    exe = h.tool_path("yt-dlp")
    assert exe == h.BIN_DIR / h.tool_layout()["yt-dlp"]
    assert os.access(exe, os.X_OK) and os.access(h.BIN_DIR / "yt-dlp" / "_internal" / "Python", os.X_OK)
    assert h.read_tool_version("yt-dlp") == "2026.11.01"
    assert not list(h.BIN_DIR.glob(".yt-dlp*"))   # no staging leftovers
    # Installing again swaps the folder in place.
    _fake_ytdlp_zip(root / "yt-dlp_macos.zip", "2026.11.05")
    h.install_tool("yt-dlp")
    assert h.read_tool_version("yt-dlp") == "2026.11.05"


def test_update_installs_only_when_newer(isolated, tool_server, monkeypatch):
    root, base = tool_server
    _fake_ytdlp_zip(root / "yt-dlp_macos.zip", "2026.11.01")
    monkeypatch.setattr(h, "tool_specs", lambda: {"yt-dlp": {"url": f"{base}/yt-dlp_macos.zip", "folder": "yt-dlp"}})
    h.install_tool("yt-dlp")
    sent = []
    host = h.Host.__new__(h.Host)
    host.send = sent.append
    host.tools_lock = threading.Lock()
    monkeypatch.setattr(h, "latest_ytdlp_version", lambda: "2026.11.01")
    host.do_update()
    assert sent[-1]["ok"] and "up to date" in sent[-1]["output"]
    _fake_ytdlp_zip(root / "yt-dlp_macos.zip", "2026.11.05")
    monkeypatch.setattr(h, "latest_ytdlp_version", lambda: "2026.11.05")
    host.do_update()
    assert sent[-1]["ok"] and sent[-1]["version"] == "2026.11.05" and "Updated" in sent[-1]["output"]


def test_tool_that_will_not_run_is_reported(chrome):
    (chrome.home / "bin" / "deno").write_text("#!/bin/sh\nexit 1\n")
    chrome.send({"type": "hello"})
    hello = chrome.wait_for(lambda m: m["type"] == "hello")
    assert hello["tools"]["deno"] == "not working" and hello["missing"] == []

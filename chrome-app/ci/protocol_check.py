"""Talk to a built helper the way Chrome does, and download from a local server.

    python3 chrome-app/ci/protocol_check.py "path/to/YT Downloader.app/Contents/MacOS/YT Downloader"
    python  chrome-app/ci/protocol_check.py "path\\to\\YT Downloader\\YT Downloader.exe"

Needs YTDL_HOME pointing at a folder where `--install-tools` already ran.
Checks: hello reports every tool, a video and an audio download both land in
the downloads folder with the right codecs, and a wrong caller is refused.
"""
from __future__ import annotations

import functools
import http.server
import json
import os
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

EXT_ORIGIN = "chrome-extension://dchdeelhpdnkdichogpodkgkhojfehph/"
WINDOWS = sys.platform == "win32"



class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def main(app: str) -> None:
    home = Path(os.environ["YTDL_HOME"])
    tools = home / "bin"
    ffmpeg = tools / "ffmpeg" / "ffmpeg.exe" if WINDOWS else tools / "ffmpeg"
    ffprobe = tools / "ffmpeg" / "ffprobe.exe" if WINDOWS else tools / "ffprobe"
    work = Path(tempfile.mkdtemp())
    downloads = work / "Downloads"
    media = work / "media"
    media.mkdir()
    for encoder in ("libx264", "h264_videotoolbox"):
        made = subprocess.run([str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
                               "-f", "lavfi", "-i", "testsrc=size=640x360:rate=25", "-f", "lavfi", "-i",
                               "sine=frequency=440", "-t", "5", "-c:v", encoder, "-pix_fmt", "yuv420p",
                               "-c:a", "aac", str(media / "テスト clip.mp4")])
        if made.returncode == 0:
            break
    else:
        raise SystemExit("no H.264 encoder available to make the test clip")
    handler = functools.partial(QuietHandler, directory=str(media))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/%E3%83%86%E3%82%B9%E3%83%88%20clip.mp4"

    test_env = {"YTDL_HOME": str(home), "YTDL_DOWNLOADS": str(downloads), "YTDL_ALLOW_ANY_URL": "1",
                "YTDL_NO_OPEN": "1"}
    if WINDOWS:
        # Chrome passes its own environment, and a --parent-window argument.
        env = {**os.environ, **test_env}
        caller = [app, EXT_ORIGIN, "--parent-window=0"]
    else:
        # macOS: Chrome starts hosts with a bare environment (no UTF-8 locale, minimal PATH).
        env = {"HOME": os.environ["HOME"], "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", **test_env}
        caller = [app, EXT_ORIGIN]
    proc = subprocess.Popen(caller, stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env)

    def send(message: dict) -> None:
        data = json.dumps(message).encode()
        proc.stdin.write(struct.pack("=I", len(data)) + data)
        proc.stdin.flush()

    def receive() -> dict:
        header = proc.stdout.read(4)
        if len(header) < 4:
            raise SystemExit("helper closed the connection")
        return json.loads(proc.stdout.read(struct.unpack("=I", header)[0]))

    send({"type": "hello"})
    hello = receive()
    print("hello:", json.dumps(hello, ensure_ascii=False))
    assert hello["missing"] == [], hello
    assert all(hello["tools"].values()), hello

    results = {}
    for job_id, mode in (("v", "video"), ("a", "audio")):
        send({"type": "download", "id": job_id, "url": url, "mode": mode})
        deadline = time.time() + 180
        while time.time() < deadline:
            message = receive()
            if message.get("type") == "job" and message["job"]["id"] == job_id and \
                    message["job"]["status"] in ("done", "error", "cancelled"):
                results[mode] = message["job"]
                print(f"{mode}:", json.dumps(message["job"], ensure_ascii=False))
                break
        assert results.get(mode, {}).get("status") == "done", results.get(mode)

    proc.stdin.close()
    assert proc.wait(timeout=30) == 0

    files = sorted(p.name for p in downloads.iterdir())
    print("files:", files)
    assert files == ["テスト clip [テスト clip].mp3", "テスト clip [テスト clip].mp4"], files
    codecs = subprocess.run([str(ffprobe), "-v", "error", "-show_entries", "stream=codec_name",
                             "-of", "csv=p=0", results["video"]["file"]], capture_output=True, text=True).stdout.split()
    assert codecs == ["h264", "aac"], codecs

    refused = subprocess.run([app, "chrome-extension://someoneelse/"], input=b"", env=env)
    assert refused.returncode == 1
    print("PROTOCOL CHECK PASSED")


if __name__ == "__main__":
    main(sys.argv[1])

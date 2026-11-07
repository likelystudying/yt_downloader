#!/usr/bin/env python3
"""
YT Downloader helper for macOS and Windows.

One program with several jobs:

  chrome-extension://...   Chrome started us. Talk to the extension over
                           native messaging (stdin/stdout) and run downloads.
  (no arguments)           Double-clicked. Register with Chrome, copy the
                           extension, download yt-dlp, FFmpeg and Deno.
  --register               Register with Chrome and copy the extension (no dialogs).
  --install-tools          Download yt-dlp, FFmpeg, FFprobe and Deno.
  --show-next-steps        Explain how to add the extension (Windows installer).
  --selftest               Check that the tools run (used by the build workflows).
  --paths                  Print where things live.
  --uninstall              Remove the Chrome registration and the support folder.
  --version                Print the helper version.

Its files live in ~/Library/Application Support/YT Downloader (macOS) or
%LOCALAPPDATA%\\YT Downloader (Windows). Downloads go to Downloads/YT Downloader
unless you choose another folder.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import signal
import ssl
import stat
import struct
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
import zipfile
from collections import deque
from pathlib import Path
from urllib.parse import parse_qs, urlparse

APP_NAME = "YT Downloader"
VERSION = "1.1.0"
HOST_NAME = "com.likelystudying.ytdownloader"
EXTENSION_ID = "dchdeelhpdnkdichogpodkgkhojfehph"
EXTENSION_ORIGIN = f"chrome-extension://{EXTENSION_ID}/"
RELEASES_URL = "https://github.com/likelystudying/yt_downloader/releases"

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"
FROZEN = getattr(sys, "frozen", False)
HOME = Path.home()
# Child processes on Windows: no console windows popping up.
NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if IS_WIN else {}


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else default


def _default_support_dir() -> Path:
    if IS_WIN:
        return Path(os.environ.get("LOCALAPPDATA") or HOME / "AppData" / "Local") / APP_NAME
    return HOME / "Library" / "Application Support" / APP_NAME


def _downloads_folder() -> Path:
    """The user's Downloads folder (on Windows it can be moved, so ask the shell)."""
    if IS_WIN:
        try:
            import ctypes
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                            ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

            known = uuid.UUID("374DE290-123F-4565-9164-39C4925E467B")  # FOLDERID_Downloads
            guid = GUID(known.time_low, known.time_mid, known.time_hi_version,
                        (ctypes.c_ubyte * 8).from_buffer_copy(known.bytes[8:]))
            out = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(out)) == 0:
                folder = out.value
                ctypes.windll.ole32.CoTaskMemFree(out)
                if folder:
                    return Path(folder)
        except Exception:
            pass
    return HOME / "Downloads"


SUPPORT_DIR = _env_path("YTDL_HOME", _default_support_dir())
BIN_DIR = SUPPORT_DIR / "bin"
WORK_DIR = SUPPORT_DIR / "work"  # per-job scratch folders; partial files never reach Downloads
EXTENSION_DIR = SUPPORT_DIR / "Chrome Extension"
CONFIG_FILE = SUPPORT_DIR / "config.json"
LOG_FILE = SUPPORT_DIR / "helper.log"
DEFAULT_DOWNLOAD_DIR = _env_path("YTDL_DOWNLOADS", _downloads_folder() / APP_NAME)

# Test switches. Chrome never sets these.
ALLOW_ANY_URL = os.environ.get("YTDL_ALLOW_ANY_URL") == "1"
NO_OPEN = os.environ.get("YTDL_NO_OPEN") == "1"
# End-to-end tests: download this URL instead of the (YouTube) one the extension sent.
URL_OVERRIDE = os.environ.get("YTDL_URL_OVERRIDE")

# macOS: Chromium browsers whose NativeMessagingHosts folder we register in
# (relative to ~/Library/Application Support). Chrome is always registered;
# the others only if that browser has been used on this Mac.
CHROME_DIR = "Google/Chrome"
OTHER_BROWSER_DIRS = [
    "Google/Chrome Beta",
    "Google/Chrome Dev",
    "Google/Chrome Canary",
    "Chromium",
    "BraveSoftware/Brave-Browser",
    "Microsoft Edge",
]

# Windows: registry keys (under HKEY_CURRENT_USER) that point Chromium browsers at
# our manifest. Chrome and Edge always; the others if installed.
WIN_BROWSER_KEYS = {
    "Chrome": r"Software\Google\Chrome",
    "Edge": r"Software\Microsoft\Edge",
    "Brave": r"Software\BraveSoftware\Brave-Browser",
    "Chromium": r"Software\Chromium",
}
WIN_ALWAYS = {"Chrome", "Edge"}

TOOL_ORDER = ["yt-dlp", "ffmpeg", "ffprobe", "deno"]
REQUIRED_TOOLS = {"yt-dlp", "ffmpeg", "ffprobe"}  # Deno is strongly recommended, not fatal
VERSION_ARGS = {"yt-dlp": ["--version"], "ffmpeg": ["-version"], "ffprobe": ["-version"], "deno": ["--version"]}

ACTIVE_STATUSES = {"queued", "preparing", "running", "processing"}

# Markers we ask yt-dlp to print so its output is easy to parse.
P_PROGRESS = "@@P "
P_POSTPROCESS = "@@PP "
P_TITLE = "@@T "
P_FILE = "@@F "


# ----------------------------------------------------------------------------
# Small utilities
# ----------------------------------------------------------------------------

_log_lock = threading.Lock()


def log(message: str) -> None:
    try:
        SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
        with _log_lock:
            if LOG_FILE.exists() and LOG_FILE.stat().st_size > 1_000_000:
                LOG_FILE.replace(LOG_FILE.with_name("helper.old.log"))
            with LOG_FILE.open("a", encoding="utf-8") as fh:
                fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except OSError:
        pass


def load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


_config_lock = threading.Lock()


def update_config(**changes) -> dict:
    with _config_lock:
        cfg = load_config()
        cfg.update(changes)
        SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_FILE.with_name("config.json.tmp")
        tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(CONFIG_FILE)
        return cfg


def download_dir() -> Path:
    custom = load_config().get("download_dir")
    return Path(custom) if custom else DEFAULT_DOWNLOAD_DIR


def arch() -> str:
    machine = platform.machine().lower()
    return "arm64" if machine in ("arm64", "aarch64") else "x86_64"


def tool_layout() -> dict:
    """Where each tool's executable lives, relative to BIN_DIR."""
    if IS_WIN:
        # yt-dlp and FFmpeg are folders (an .exe plus the files it loads).
        return {"yt-dlp": "yt-dlp/yt-dlp.exe", "ffmpeg": "ffmpeg/ffmpeg.exe",
                "ffprobe": "ffmpeg/ffprobe.exe", "deno": "deno.exe"}
    return {"yt-dlp": "yt-dlp/yt-dlp_macos", "ffmpeg": "ffmpeg", "ffprobe": "ffprobe", "deno": "deno"}


def tool_path(name: str) -> Path:
    return BIN_DIR / tool_layout()[name]


def tool_env() -> dict:
    """Environment for yt-dlp and friends.

    Apps started from Finder or by Chrome get a minimal PATH, and often no
    UTF-8 locale. Put our tools first and force UTF-8 so Japanese (and other
    non-ASCII) titles survive.
    """
    env = os.environ.copy()
    default_path = "" if IS_WIN else "/usr/bin:/bin:/usr/sbin:/sbin"
    env["PATH"] = os.pathsep.join([str(BIN_DIR), str(tool_path("ffmpeg").parent),
                                   env.get("PATH") or default_path])
    env["PYTHONIOENCODING"] = "utf-8"
    env.setdefault("LANG", "en_US.UTF-8")
    env.setdefault("LC_ALL", env["LANG"])
    return env


def open_in_finder(path: Path, reveal: bool = False) -> None:
    if NO_OPEN:
        log(f"(test) open {'-R ' if reveal else ''}{path}")
        return
    if IS_MAC:
        subprocess.run(["open", "-R", str(path)] if reveal else ["open", str(path)],
                       stdin=subprocess.DEVNULL, capture_output=True)
    elif IS_WIN:
        if reveal:
            # explorer needs the quotes exactly like this, so pass one string.
            subprocess.Popen(f'explorer /select,"{path}"')
        else:
            os.startfile(str(path))  # noqa: S606 - opens the folder in File Explorer
    else:
        subprocess.run(["xdg-open", str(path.parent if reveal else path)],
                       stdin=subprocess.DEVNULL, capture_output=True)


def osascript(lines: list[str], args: list[str]) -> subprocess.CompletedProcess:
    cmd = ["osascript"]
    for line in lines:
        cmd += ["-e", line]
    return subprocess.run(cmd + args, stdin=subprocess.DEVNULL, capture_output=True, text=True)


def message_box(text: str) -> None:
    """Windows: a plain OK message box, kept on top so it isn't lost behind Chrome."""
    if IS_WIN:
        import ctypes
        MB_ICONINFORMATION, MB_SETFOREGROUND, MB_TOPMOST = 0x40, 0x10000, 0x40000
        ctypes.windll.user32.MessageBoxW(None, text, APP_NAME, MB_ICONINFORMATION | MB_SETFOREGROUND | MB_TOPMOST)
    else:
        dialog(text)


def copy_to_clipboard(text: str) -> None:
    if IS_MAC:
        subprocess.run(["pbcopy"], input=text, text=True, capture_output=True)
    elif IS_WIN:
        env = {**os.environ, "YTDL_CLIP": text}  # via the environment: no quoting problems
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                        "Set-Clipboard -Value $env:YTDL_CLIP"],
                       env=env, stdin=subprocess.DEVNULL, capture_output=True, **NO_WINDOW)


def dialog(text: str, buttons: tuple[str, ...] = ("OK",), default: str | None = None) -> str:
    """macOS: show a native dialog; return the clicked button ("" if cancelled)."""
    if not IS_MAC:
        print(text)
        return default or buttons[-1]
    default = default or buttons[-1]
    button_refs = ", ".join(f"(item {i + 2} of argv)" for i in range(len(buttons)))
    default_ref = f"(item {buttons.index(default) + 2} of argv)"
    lines = [
        "on run argv",
        "activate",
        "set r to display dialog (item 1 of argv) with title "
        f'"{APP_NAME}" buttons {{{button_refs}}} default button {default_ref} with icon note',
        "return button returned of r",
        "end run",
    ]
    return osascript(lines, [text, *buttons]).stdout.strip()


# ----------------------------------------------------------------------------
# URL validation (same rules as the original yt-dlp-gui.py)
# ----------------------------------------------------------------------------

YOUTUBE_HOSTS = {"youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}


def validate_url(url: str) -> str | None:
    """Return an error message, or None if the URL is a YouTube video."""
    if not url:
        return "No URL given."
    try:
        parsed = urlparse(url)
    except ValueError:
        return "That isn't a valid URL."
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return "The URL must start with http:// or https://."
    if ALLOW_ANY_URL:
        return None
    host = parsed.netloc.lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    if host not in YOUTUBE_HOSTS:
        return "Only YouTube links are supported."
    parts = [p for p in parsed.path.split("/") if p]
    video_id = ""
    if host == "youtu.be":
        video_id = parts[0] if parts else ""
    elif parts and parts[0] == "watch":
        video_id = parse_qs(parsed.query).get("v", [""])[0]
    elif len(parts) >= 2 and parts[0] in ("shorts", "embed", "live"):
        video_id = parts[1]
    if len(video_id.strip()) < 6:
        return "This link isn't a single YouTube video."
    return None


# ----------------------------------------------------------------------------
# Tools: yt-dlp, FFmpeg, FFprobe, Deno
# ----------------------------------------------------------------------------

def tool_specs() -> dict:
    if IS_WIN:
        return {
            # Unpacked build (yt-dlp.exe + _internal), like on the Mac.
            "yt-dlp": {"url": "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_win.zip",
                       "folder": "yt-dlp"},
            # yt-dlp's own FFmpeg build; "shared" = ffmpeg.exe + ffprobe.exe + DLLs (91 MB vs 201 MB).
            "ffmpeg": {"url": "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/"
                              "ffmpeg-master-latest-win64-gpl-shared.zip", "folder": "ffmpeg"},
            "ffprobe": {"provided_by": "ffmpeg"},
            "deno": {"url": "https://github.com/denoland/deno/releases/latest/download/"
                            "deno-x86_64-pc-windows-msvc.zip", "member": "deno.exe"},
        }
    arm = arch() == "arm64"
    deno_arch = "aarch64" if arm else "x86_64"
    ff_arch = "arm64" if arm else "amd64"
    ff_base = f"https://ffmpeg.martin-riedl.de/redirect/latest/macos/{ff_arch}/release"
    return {
        # The *unpacked* universal macOS build (a folder: yt-dlp_macos + _internal/).
        # Not the single-file yt-dlp_macos: that one unpacks its own Python into a
        # temp folder on every run, and when Chrome is the parent process macOS
        # quarantines those fresh files and refuses to load them ("Python.framework
        # is damaged").
        "yt-dlp": {"url": "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_macos.zip",
                   "folder": "yt-dlp"},
        # Static builds, signed by their maintainer.
        "ffmpeg": {"url": f"{ff_base}/ffmpeg.zip", "member": "ffmpeg"},
        "ffprobe": {"url": f"{ff_base}/ffprobe.zip", "member": "ffprobe"},
        # JavaScript runtime yt-dlp needs for full YouTube support.
        "deno": {"url": f"https://github.com/denoland/deno/releases/latest/download/deno-{deno_arch}-apple-darwin.zip",
                 "member": "deno"},
    }


def _ssl_context() -> ssl.SSLContext:
    # A frozen app can't use the build machine's certificate paths, so use
    # certifi's bundle (shipped inside the app) unless SSL_CERT_FILE is set.
    cafile = os.environ.get("SSL_CERT_FILE")
    if cafile and os.path.exists(cafile):
        return ssl.create_default_context(cafile=cafile)
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _open_url(url: str, timeout: int = 60):
    request = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{VERSION}"})
    return urllib.request.urlopen(request, context=_ssl_context(), timeout=timeout)


def fetch(url: str, dest: Path, on_progress=None) -> None:
    tmp = dest.with_name(dest.name + ".download")
    received, last = 0, 0.0
    with _open_url(url) as response, tmp.open("wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        while True:
            chunk = response.read(256 * 1024)
            if not chunk:
                break
            out.write(chunk)
            received += len(chunk)
            if on_progress and time.monotonic() - last > 0.25:
                last = time.monotonic()
                on_progress(received, total)
    if on_progress:
        on_progress(received, received)
    tmp.replace(dest)


def clear_quarantine(path: Path) -> None:
    """Remove macOS's "downloaded from the internet" flag from our own tools.

    The helper runs as a child of Chrome, and macOS tags every file a Chrome
    child writes as "downloaded by Chrome". Quarantined helper binaries that
    aren't notarized are then refused ("is damaged and can't be opened").
    """
    if IS_MAC and path.exists():
        subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(path)],
                       stdin=subprocess.DEVNULL, capture_output=True)


def extract_zip(archive: Path, dest: Path) -> None:
    """Unpack keeping permissions (and symlinks): ditto on macOS, zipfile elsewhere."""
    dest.mkdir(parents=True, exist_ok=True)
    if IS_MAC and shutil.which("ditto"):
        subprocess.run(["ditto", "-x", "-k", str(archive), str(dest)], check=True,
                       stdin=subprocess.DEVNULL, capture_output=True)
        return
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            target = dest / info.filename
            mode = info.external_attr >> 16
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif stat.S_ISLNK(mode):
                target.parent.mkdir(parents=True, exist_ok=True)
                os.symlink(zf.read(info).decode(), target)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, target.open("wb") as out:
                    shutil.copyfileobj(src, out)
                if mode & 0o777:
                    target.chmod(mode & 0o777)


def install_tool(name: str, on_progress=None) -> None:
    spec = tool_specs()[name]
    if "provided_by" in spec:  # e.g. ffprobe.exe comes in the FFmpeg folder on Windows
        install_tool(spec["provided_by"], on_progress)
        return
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    if "folder" in spec:
        _install_folder_tool(name, spec, on_progress)
    else:
        dest = tool_path(name)
        staged = dest.with_name(dest.name + ".new")
        if "member" in spec:
            archive = BIN_DIR / f"{name}.zip"
            fetch(spec["url"], archive, on_progress)
            try:
                with zipfile.ZipFile(archive) as zf:
                    member = next((m for m in zf.namelist()
                                   if not m.endswith("/") and Path(m).name == spec["member"]), None)
                    if member is None:
                        raise RuntimeError(f"{spec['member']} was not found in the download")
                    with zf.open(member) as src, staged.open("wb") as out:
                        shutil.copyfileobj(src, out)
            finally:
                archive.unlink(missing_ok=True)
        else:
            fetch(spec["url"], staged, on_progress)
        staged.chmod(0o755)
        clear_quarantine(staged)
        staged.replace(dest)
    if name == "yt-dlp":  # a fresh download is current; next automatic update check in a few days
        update_config(last_update_check=time.time())


def _install_folder_tool(name: str, spec: dict, on_progress=None) -> None:
    """Install a tool that ships as a folder (an executable plus the files it loads).

    The folder is wherever the executable sits in the archive: the top for
    yt-dlp, <name>/bin for the FFmpeg build.
    """
    final = BIN_DIR / spec["folder"]
    staging = BIN_DIR / f".{name}.new"
    archive = BIN_DIR / f".{name}.zip"
    shutil.rmtree(staging, ignore_errors=True)
    fetch(spec["url"], archive, on_progress)
    try:
        extract_zip(archive, staging)
    finally:
        archive.unlink(missing_ok=True)
    exe_name = Path(tool_layout()[name]).name
    found = sorted(staging.rglob(exe_name), key=lambda p: len(p.parts))
    if not found:
        shutil.rmtree(staging, ignore_errors=True)
        raise RuntimeError(f"{exe_name} was not found in the download")
    exe = found[0]
    exe.chmod(exe.stat().st_mode | 0o755)
    clear_quarantine(staging)
    if exe.parent != staging:  # keep just the folder that holds the executable
        inner = BIN_DIR / f".{name}.inner"
        shutil.rmtree(inner, ignore_errors=True)
        exe.parent.rename(inner)
        shutil.rmtree(staging, ignore_errors=True)
        inner.rename(staging)
    # Swap in the new folder; a running download keeps using the old files.
    old = BIN_DIR / f".{name}.old"
    shutil.rmtree(old, ignore_errors=True)
    if final.is_dir() and not final.is_symlink():
        final.rename(old)
    elif final.exists() or final.is_symlink():
        final.unlink()  # a single-file build from version 1.0.0
    staging.rename(final)
    shutil.rmtree(old, ignore_errors=True)


def remove_legacy_tools() -> None:
    """Version 1.0.0 installed the single-file yt-dlp at bin/yt-dlp; it can't run under Chrome."""
    legacy = BIN_DIR / "yt-dlp"
    if legacy.is_file():
        legacy.unlink()
        log("removed single-file yt-dlp from 1.0.0")


def latest_ytdlp_version() -> str | None:
    try:
        with _open_url("https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest", timeout=20) as response:
            return json.loads(response.read().decode()).get("tag_name")
    except Exception as exc:
        log(f"couldn't check the latest yt-dlp version: {exc!r}")
        return None


def prepare_tools() -> None:
    """Run before using the tools: drop the 1.0.0 single-file yt-dlp and clear quarantine."""
    remove_legacy_tools()
    clear_quarantine(BIN_DIR)


def read_tool_version(name: str) -> str | None:
    path = tool_path(name)
    if not path.exists():
        return None
    try:
        result = subprocess.run([str(path), *VERSION_ARGS[name]], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=120,
                                stdin=subprocess.DEVNULL, env=tool_env(), **NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log(f"{name} --version failed: {exc}")
        return None
    if result.returncode != 0:
        log(f"{name} --version exited {result.returncode}: {result.stderr.strip()[:300]}")
        return None
    first = (result.stdout.strip().splitlines() or [""])[0]
    if name in ("ffmpeg", "ffprobe"):
        match = re.search(r"version (\S+)", first)
        return match.group(1) if match else first
    if name == "deno":
        return first.replace("deno ", "").split(" ")[0]
    return first


def refresh_versions(names=TOOL_ORDER) -> dict:
    versions = dict(load_config().get("versions") or {})
    for name in names:
        versions[name] = read_tool_version(name)
    update_config(versions=versions)
    return versions


def missing_tools() -> list[str]:
    return [name for name in TOOL_ORDER if not tool_path(name).exists()]


# ----------------------------------------------------------------------------
# yt-dlp command line
# ----------------------------------------------------------------------------

def build_command(url: str, mode: str, work_dir: Path) -> list[str]:
    """yt-dlp command for one job.

    yt-dlp writes into a private per-job work folder, never into Downloads:
    it reuses (and then deletes) same-named files it finds in its output
    folder, so audio after video of the same clip would delete the MP4.
    """
    cmd = [
        str(tool_path("yt-dlp")),
        "--ignore-config",
        "--no-playlist",          # a watch?v=..&list=.. link downloads one video, not the playlist
        "--color", "never",
        "--newline",
        "--progress",
        "--no-simulate",
        "--no-mtime",             # file date = download date, so it sorts as new in Finder
        "--progress-template",
        f"download:{P_PROGRESS}%(progress.downloaded_bytes)s|%(progress.total_bytes)s|"
        "%(progress.total_bytes_estimate)s|%(progress.speed)s|%(progress.eta)s",
        "--progress-template", f"postprocess:{P_POSTPROCESS}%(progress.postprocessor)s|%(progress.status)s",
        "--print", f"before_dl:{P_TITLE}%(id)s|%(title)s",
        "--print", f"after_move:{P_FILE}%(filepath)s",
        "-P", str(work_dir),
        # Windows paths are limited to 260 characters, so keep names shorter there.
        "-o", "%(title).120B [%(id)s].%(ext)s" if IS_WIN else "%(title).180B [%(id)s].%(ext)s",
    ]
    if tool_path("ffmpeg").exists():
        cmd += ["--ffmpeg-location", str(tool_path("ffmpeg").parent)]
    if tool_path("deno").exists():
        cmd += ["--js-runtimes", f"deno:{tool_path('deno')}"]
    # -t mp3: extract audio as MP3.  -t mp4: H.264/AAC in MP4, which plays in
    # QuickTime and Photos on every Mac (the original picked any MP4 codec).
    cmd += ["-t", "mp3" if mode == "audio" else "mp4"]
    cmd += ["--", url]
    return cmd


def _num(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def friendly_error(message: str) -> str:
    text = message.strip()
    lower = text.lower()
    if "confirm you" in lower and "bot" in lower:
        return "YouTube asked to confirm you're not a bot. Wait a while and try again."
    if "failed to load python shared library" in lower or "library load disallowed" in lower:
        return "macOS blocked yt-dlp from starting. Click “Update yt-dlp” to reinstall it, then try again."
    if "private video" in lower:
        return "This video is private."
    if "video unavailable" in lower:
        return "This video is unavailable."
    if "sign in to confirm your age" in lower:
        return "This video is age-restricted and needs a signed-in account."
    if "requested format is not available" in lower or "nsig" in lower or "player response" in lower:
        return f"{text}  (Try “Update yt-dlp”, then download again.)"
    return text or "Download failed."


# ----------------------------------------------------------------------------
# Native messaging host
# ----------------------------------------------------------------------------

class Host:
    """Reads requests from the extension and runs one download at a time."""

    def __init__(self, inp, out):
        self.inp = inp
        self.out = out
        self.write_lock = threading.Lock()
        self.cv = threading.Condition()
        self.tools_lock = threading.Lock()
        self.jobs: dict[str, dict] = {}
        self.queue: deque[str] = deque()
        self.current: tuple[dict, subprocess.Popen] | None = None
        self.stopping = False
        self.worker = threading.Thread(target=self._worker, daemon=True)
        self.worker.start()

    # --- protocol --------------------------------------------------------

    def send(self, message: dict) -> None:
        data = json.dumps(message, ensure_ascii=False).encode("utf-8")
        try:
            with self.write_lock:
                self.out.write(struct.pack("=I", len(data)))
                self.out.write(data)
                self.out.flush()
        except (BrokenPipeError, OSError, ValueError):
            self.stopping = True

    def read_message(self) -> dict | None:
        header = self.inp.read(4)
        if len(header) < 4:
            return None
        (length,) = struct.unpack("=I", header)
        data = self.inp.read(length)
        if len(data) < length:
            return None
        return json.loads(data.decode("utf-8"))

    def run(self) -> None:
        log(f"helper {VERSION} started")
        try:
            while not self.stopping:
                message = self.read_message()
                if message is None:
                    break
                try:
                    self.handle(message)
                except Exception as exc:  # keep running on a bad request
                    log(f"error handling {message.get('type')}: {exc!r}")
                    self.send({"type": "error", "message": str(exc)})
        finally:
            self.shutdown()
            log("helper stopped")

    def handle(self, message: dict) -> None:
        kind = message.get("type")
        if kind == "hello":
            prepare_tools()
            self.send(self.status_message("hello"))
            self.maybe_auto_update()
        elif kind == "ping":
            self.send({"type": "pong"})
        elif kind == "download":
            self.enqueue(message)
        elif kind == "cancel":
            self.cancel(str(message.get("id", "")))
        elif kind == "setup":
            self.spawn(self.do_setup)
        elif kind == "update":
            self.spawn(self.do_update)
        elif kind == "open_folder":
            folder = download_dir()
            folder.mkdir(parents=True, exist_ok=True)
            open_in_finder(folder)
        elif kind == "reveal":
            self.reveal(message.get("path") or "")
        elif kind == "choose_folder":
            self.spawn(self.do_choose_folder)
        else:
            self.send({"type": "error", "message": f"Unknown request: {kind}"})

    @staticmethod
    def spawn(target) -> None:
        threading.Thread(target=target, daemon=True).start()

    def status_message(self, kind: str) -> dict:
        cfg = load_config()
        versions = cfg.get("versions") or {}
        installed = {name: tool_path(name).exists() for name in TOOL_ORDER}
        # Fill in versions we haven't read yet (first run after an install).
        unknown = [n for n in TOOL_ORDER if installed[n] and not versions.get(n)]
        if unknown:
            versions = refresh_versions(unknown)
        return {
            "type": kind,
            "version": VERSION,
            "tools": {n: ((versions.get(n) or "not working") if installed[n] else None) for n in TOOL_ORDER},
            "missing": [n for n in TOOL_ORDER if not installed[n]],
            "downloadDir": str(download_dir()),
            "lastUpdateCheck": cfg.get("last_update_check"),
            "platform": sys.platform,
            "arch": arch(),
        }

    # --- jobs ------------------------------------------------------------

    def emit_job(self, job: dict, force: bool = True) -> None:
        now = time.monotonic()
        if not force and now - job.get("_sent", 0.0) < 0.25:
            return
        job["_sent"] = now
        self.send({"type": "job", "job": {k: v for k, v in job.items() if not k.startswith("_")}})

    def enqueue(self, message: dict) -> None:
        url = str(message.get("url") or "").strip()
        mode = message.get("mode")
        job = {
            "id": str(message.get("id") or uuid.uuid4())[:64],
            "url": url,
            "mode": mode if mode in ("video", "audio") else "video",
            "title": message.get("title") or url,
            "status": "queued",
            "phase": None,
            "percent": None,
            "part": 0,
            "speed": None,
            "eta": None,
            "file": None,
            "error": None,
        }
        problem = validate_url(url)
        if mode not in ("video", "audio"):
            problem = "Choose video or audio."
        if problem:
            job.update(status="error", error=problem)
            self.emit_job(job)
            return
        with self.cv:
            self.jobs[job["id"]] = job
            self.queue.append(job["id"])
            self.cv.notify()
        self.emit_job(job)

    def _worker(self) -> None:
        while True:
            with self.cv:
                while not self.queue and not self.stopping:
                    self.cv.wait()
                if self.stopping:
                    return
                job = self.jobs[self.queue.popleft()]
                if job["status"] != "queued":
                    continue
            try:
                self.run_job(job)
            except Exception as exc:
                log(f"job {job['id']} crashed: {exc!r}")
                job.update(status="error", error=str(exc))
                self.emit_job(job)

    def run_job(self, job: dict) -> None:
        prepare_tools()
        if missing_tools():
            job.update(status="preparing", phase="Installing components…")
            self.emit_job(job)
            failures = self.ensure_tools()
            if REQUIRED_TOOLS & failures.keys():
                job.update(status="error", error="Couldn't download the tools it needs. Check your internet "
                                                 "connection and try again.")
                self.emit_job(job)
                return
            if job.get("_cancel"):
                job.update(status="cancelled")
                self.emit_job(job)
                return

        work_dir = WORK_DIR / uuid.uuid4().hex[:10]  # never build paths from request data; short for Windows
        try:
            self._download(job, work_dir)
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)  # partial files go with it
        self.emit_job(job)

    def _download(self, job: dict, work_dir: Path) -> None:
        shutil.rmtree(work_dir, ignore_errors=True)
        work_dir.mkdir(parents=True)
        cmd = build_command(URL_OVERRIDE or job["url"], job["mode"], work_dir)
        log(f"job {job['id']}: {job['mode']} {job['url']}")
        job.update(status="running", phase="Starting…")
        self.emit_job(job)

        with self.tools_lock:  # don't start while yt-dlp is being updated
            process = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                cwd=str(work_dir), env=tool_env(), **child_process_options())
        with self.cv:
            self.current = (job, process)
            cancelled_early = job.get("_cancel")
        if cancelled_early:
            self._kill(process)

        last_error = ""
        last_line = ""
        assert process.stdout is not None
        for raw in process.stdout:
            line = raw.rstrip("\n")
            if line.startswith(P_PROGRESS):
                self._on_progress(job, line[len(P_PROGRESS):])
            elif line.startswith(P_POSTPROCESS):
                name = line[len(P_POSTPROCESS):].split("|")[0]
                job.update(status="processing", phase="Merging…" if "Merger" in name else "Converting…",
                           speed=None, eta=None)
                self.emit_job(job, force=False)
            elif line.startswith(P_TITLE):
                video_id, _, title = line[len(P_TITLE):].partition("|")
                job["_vid"] = video_id
                if title and title != "NA":
                    job["title"] = title
                self.emit_job(job)
            elif line.startswith(P_FILE):
                job["file"] = line[len(P_FILE):].strip()
            elif line.startswith("ERROR:"):
                last_error = line[len("ERROR:"):].strip()
                log(f"job {job['id']}: {line}")
            elif line.strip():
                last_line = line.strip()
                log(f"job {job['id']}: {line[:500]}")
        code = process.wait()
        with self.cv:
            self.current = None

        job.update(phase=None, speed=None, eta=None)
        if job.get("_cancel"):
            job.update(status="cancelled")
        elif code != 0:
            job.update(status="error", error=friendly_error(
                last_error or last_line or f"yt-dlp stopped with code {code}."))
        else:
            try:
                job["file"] = str(self.deliver(work_dir, job.get("file")))
                job.update(status="done", percent=100.0)
            except Exception as exc:
                log(f"job {job['id']}: moving the file failed: {exc!r}")
                job.update(status="error", error=f"Downloaded, but couldn't save to {download_dir()}: {exc}")

    @staticmethod
    def deliver(work_dir: Path, reported: str | None) -> Path:
        """Move the finished file from the work folder into the downloads folder."""
        source = Path(reported) if reported else None
        if source is None or not source.exists():
            finished = [p for p in work_dir.iterdir()
                        if p.is_file() and not p.name.endswith((".part", ".ytdl")) and ".part-Frag" not in p.name]
            if not finished:
                raise FileNotFoundError("yt-dlp didn't produce a file")
            source = max(finished, key=lambda p: p.stat().st_size)
        out_dir = download_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / source.name
        shutil.move(str(source), str(target))  # same video + same format again: replace the old copy
        return target

    def _on_progress(self, job: dict, payload: str) -> None:
        fields = payload.split("|")
        if len(fields) < 5:
            return
        done, total, estimate, speed, eta = (_num(f) for f in fields[:5])
        size = total or estimate
        percent = round(done / size * 100, 1) if done is not None and size else None
        if percent is not None:
            previous = job.get("percent")
            # Video downloads fetch two streams (video, then audio); count restarts.
            if job["part"] == 0 or (previous is not None and percent + 30 < previous):
                job["part"] += 1
            job["percent"] = min(percent, 100.0)
        phase = "Downloading"
        if job["mode"] == "video" and job["part"] >= 1:
            phase = "Downloading video" if job["part"] == 1 else "Downloading audio"
        job.update(status="running", phase=phase, speed=speed, eta=eta)
        self.emit_job(job, force=False)

    def cancel(self, job_id: str) -> None:
        with self.cv:
            job = self.jobs.get(job_id)
            if not job or job["status"] not in ACTIVE_STATUSES:
                return
            job["_cancel"] = True
            running = self.current if self.current and self.current[0] is job else None
            if job["status"] == "queued":
                job["status"] = "cancelled"
                try:
                    self.queue.remove(job_id)
                except ValueError:
                    pass
        if running:
            self._kill(running[1])
        elif job["status"] == "cancelled":
            self.emit_job(job)

    @staticmethod
    def _kill(process: subprocess.Popen) -> None:
        if IS_WIN:  # end yt-dlp and its ffmpeg children
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdin=subprocess.DEVNULL, capture_output=True, **NO_WINDOW)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)  # yt-dlp and its ffmpeg children
        except (ProcessLookupError, PermissionError):
            return
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def reveal(self, path: str) -> None:
        if not path:
            return
        target = Path(path).resolve()
        known = {j.get("file") for j in self.jobs.values()}
        inside = str(target).startswith(str(download_dir().resolve()) + os.sep)
        if target.exists() and (path in known or inside):
            open_in_finder(target, reveal=True)

    # --- tools -----------------------------------------------------------

    def ensure_tools(self, force: bool = False) -> dict:
        failures: dict[str, str] = {}
        with self.tools_lock:
            for name in TOOL_ORDER:
                if tool_path(name).exists() and not force:
                    continue
                self.send({"type": "setup_progress", "tool": name, "received": 0, "total": 0})
                try:
                    install_tool(name, lambda got, total, n=name: self.send(
                        {"type": "setup_progress", "tool": n, "received": got, "total": total}))
                    log(f"installed {name}")
                except Exception as exc:
                    failures[name] = str(exc)
                    log(f"installing {name} failed: {exc!r}")
            refresh_versions()
        status = self.status_message("setup_done")
        status.update(ok=not failures, failures=failures)
        self.send(status)
        return failures

    def do_setup(self) -> None:
        self.ensure_tools()

    def do_update(self, quiet: bool = False) -> None:
        """Install the latest yt-dlp release if it's newer (or the current one doesn't run).

        The unpacked build can't update itself with -U, so download it again.
        """
        prepare_tools()
        if IS_WIN and self.current:
            # Windows can't replace files that a running download is using.
            if not quiet:
                self.send({"type": "update_done", "ok": False, "quiet": quiet, "version": None,
                           "output": "Finish or cancel the current download, then click Update again."})
            return
        with self.tools_lock:
            current = read_tool_version("yt-dlp")
            latest = latest_ytdlp_version()
            if current and latest and current == latest:
                ok, output = True, f"yt-dlp is up to date ({current})."
            elif current and not latest and quiet:
                ok, output = True, ""  # couldn't check; try again next time
            else:
                try:
                    install_tool("yt-dlp", lambda got, total: self.send(
                        {"type": "setup_progress", "tool": "yt-dlp", "received": got, "total": total}))
                    new = read_tool_version("yt-dlp")
                    ok = new is not None
                    output = f"Updated yt-dlp to {new}." if ok else "Updated, but yt-dlp doesn't run. See the log."
                except Exception as exc:
                    ok, output = False, f"Couldn't download yt-dlp: {exc}"
            log(f"update: {output}")
            update_config(last_update_check=time.time())
            versions = refresh_versions(["yt-dlp"])
        self.send({"type": "update_done", "ok": ok, "quiet": quiet,
                   "output": output, "version": versions.get("yt-dlp")})

    def maybe_auto_update(self) -> None:
        """Keep yt-dlp current: YouTube changes often break old versions."""
        last = load_config().get("last_update_check") or 0
        busy = self.current is not None or bool(self.queue)
        if tool_path("yt-dlp").exists() and not busy and time.time() - last > 3 * 24 * 3600:
            update_config(last_update_check=time.time())
            self.spawn(lambda: self.do_update(quiet=True))

    def do_choose_folder(self) -> None:
        current = download_dir()
        current.mkdir(parents=True, exist_ok=True)
        if IS_WIN:
            chosen = choose_folder_windows(current)
            if chosen:
                update_config(download_dir=chosen)
            self.send(self.status_message("config"))
            return
        if not IS_MAC:
            self.send({"type": "error", "message": "Choosing a folder isn't available here."})
            return
        result = osascript([
            "on run argv",
            "activate",
            'set f to choose folder with prompt "Save downloads to:" default location (POSIX file (item 1 of argv))',
            "return POSIX path of f",
            "end run",
        ], [str(current)])
        chosen = result.stdout.strip()
        if result.returncode == 0 and chosen:
            update_config(download_dir=chosen.rstrip("/") or "/")
        self.send(self.status_message("config"))

    # --- shutdown --------------------------------------------------------

    def shutdown(self) -> None:
        with self.cv:
            self.stopping = True
            running = self.current
            self.cv.notify_all()
        if running:
            running[0]["_cancel"] = True
            self._kill(running[1])


def child_process_options() -> dict:
    if IS_WIN:
        return {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def choose_folder_windows(current: Path) -> str | None:
    """Folder picker that stays on top of Chrome. Paths go via the environment (no quoting issues)."""
    script = (
        "[Console]::OutputEncoding = [Text.Encoding]::UTF8;"
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$owner = New-Object System.Windows.Forms.Form -Property @{TopMost=$true; ShowInTaskbar=$false};"
        "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
        "$d.Description = 'Save downloads to:';"
        "$d.SelectedPath = $env:YTDL_CURRENT;"
        "if ($d.ShowDialog($owner) -eq 'OK') { $d.SelectedPath }"
    )
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-STA", "-Command", script],
                            env={**os.environ, "YTDL_CURRENT": str(current)}, stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, encoding="utf-8", errors="replace", **NO_WINDOW)
    chosen = result.stdout.strip()
    return chosen if result.returncode == 0 and chosen else None


# ----------------------------------------------------------------------------
# Install / register / uninstall
# ----------------------------------------------------------------------------

def bundled_extension_dir() -> Path:
    if FROZEN:
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "chrome-extension"
    return Path(__file__).resolve().parent.parent / "chrome-extension"


def host_executable() -> Path:
    if FROZEN:
        return Path(sys.executable).resolve()
    # Running from source: Chrome needs an executable, so write a wrapper.
    SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    if IS_WIN:
        wrapper = SUPPORT_DIR / "ytdl-helper-dev.bat"
        wrapper.write_text(f'@"{sys.executable}" "{Path(__file__).resolve()}" %*\n')
        return wrapper
    wrapper = SUPPORT_DIR / "ytdl-helper-dev.sh"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{Path(__file__).resolve()}" "$@"\n')
    wrapper.chmod(0o755)
    return wrapper


def manifest_dirs() -> list[Path]:
    override = os.environ.get("YTDL_NM_DIRS")
    if override:
        return [Path(p) for p in override.split(os.pathsep) if p]
    base = HOME / "Library" / "Application Support"
    dirs = [base / CHROME_DIR / "NativeMessagingHosts"]
    dirs += [base / d / "NativeMessagingHosts" for d in OTHER_BROWSER_DIRS if (base / d).is_dir()]
    return dirs


def copy_extension() -> Path:
    source = bundled_extension_dir()
    if not (source / "manifest.json").exists():
        raise RuntimeError(f"Extension files not found at {source}")
    if source.resolve() != EXTENSION_DIR.resolve():
        if EXTENSION_DIR.exists():
            shutil.rmtree(EXTENSION_DIR)
        shutil.copytree(source, EXTENSION_DIR)
    return EXTENSION_DIR


def register() -> list:
    """Tell Chrome (and other Chromium browsers) where the helper is; copy the extension."""
    copy_extension()
    manifest = {
        "name": HOST_NAME,
        "description": f"{APP_NAME} helper (runs yt-dlp on this computer)",
        "path": str(host_executable()),
        "type": "stdio",
        "allowed_origins": [EXTENSION_ORIGIN],
    }
    text = json.dumps(manifest, indent=2) + "\n"
    written: list = []
    if IS_WIN and not os.environ.get("YTDL_NM_DIRS"):
        # Windows: the manifest file can live anywhere; a registry key points to it.
        manifest_file = SUPPORT_DIR / "native-messaging-host.json"
        manifest_file.write_text(text, encoding="utf-8")
        for browser, key in windows_browser_keys():
            set_registry_default(rf"{key}\NativeMessagingHosts\{HOST_NAME}", str(manifest_file))
            written.append(browser)
    else:
        for folder in manifest_dirs():
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"{HOST_NAME}.json").write_text(text, encoding="utf-8")
            written.append(folder)
    update_config(registered_path=manifest["path"], helper_version=VERSION)
    log(f"registered {manifest['path']} for {len(written)} browser(s)")
    return written


def windows_browser_keys() -> list[tuple[str, str]]:
    import winreg
    keys = []
    for browser, key in WIN_BROWSER_KEYS.items():
        if browser in WIN_ALWAYS:
            keys.append((browser, key))
            continue
        try:
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, key))
            keys.append((browser, key))
        except OSError:
            pass
    return keys


def set_registry_default(subkey: str, value: str) -> None:
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, subkey) as handle:
        winreg.SetValueEx(handle, "", 0, winreg.REG_SZ, value)


def install_tools_cli(verbose: bool = True) -> dict:
    prepare_tools()
    failures = {}
    for name in missing_tools():
        if verbose:
            print(f"Downloading {name}…", flush=True)
        try:
            install_tool(name)
        except Exception as exc:
            failures[name] = str(exc)
            if verbose:
                print(f"  failed: {exc}", flush=True)
    refresh_versions()
    return failures


def uninstall() -> None:
    if IS_WIN:
        import winreg
        for key in WIN_BROWSER_KEYS.values():
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, rf"{key}\NativeMessagingHosts\{HOST_NAME}")
            except OSError:
                pass
        shutil.rmtree(SUPPORT_DIR, ignore_errors=True)
        return
    base = HOME / "Library" / "Application Support"
    folders = set(manifest_dirs()) | {base / d / "NativeMessagingHosts" for d in [CHROME_DIR, *OTHER_BROWSER_DIRS]}
    for folder in folders:
        (folder / f"{HOST_NAME}.json").unlink(missing_ok=True)
    shutil.rmtree(SUPPORT_DIR, ignore_errors=True)


def selftest() -> int:
    ok = True
    for name in TOOL_ORDER:
        version = read_tool_version(name)
        print(f"{name:8} {version or 'NOT WORKING'}")
        ok = ok and version is not None
    with_mp3 = subprocess.run(
        [str(tool_path("ffmpeg")), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
         "sine=frequency=440:duration=1", "-c:a", "libmp3lame", "-f", "mp3", "-y", os.devnull],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, **NO_WINDOW)
    print(f"mp3 encoder {'ok' if with_mp3.returncode == 0 else 'MISSING: ' + with_mp3.stderr.strip()}")
    ok = ok and with_mp3.returncode == 0
    print("selftest", "passed" if ok else "FAILED")
    return 0 if ok else 1


def gui_install() -> None:
    """What happens when the app is double-clicked in Finder."""
    if FROZEN:
        exe = str(Path(sys.executable).resolve())
        if "/AppTranslocation/" in exe or exe.startswith("/Volumes/"):
            dialog("Please drag “YT Downloader” into your Applications folder first, "
                   "then open it again from there.")
            return
        in_applications = exe.startswith("/Applications/") or exe.startswith(str(HOME / "Applications") + "/")
        if not in_applications:
            choice = dialog("“YT Downloader” isn't in your Applications folder.\n\n"
                            "Chrome will look for it where it is now, so moving it later "
                            "will break the extension. Best: quit, move it to Applications, "
                            "and open it again.", buttons=("Quit", "Install Here Anyway"), default="Quit")
            if choice != "Install Here Anyway":
                return
    if FROZEN:
        clear_quarantine(Path(sys.executable).resolve().parents[2])  # our .app, now that it's approved
    prepare_tools()
    try:
        register()
    except Exception as exc:
        log(f"register failed: {exc!r}")
        dialog(f"Couldn't register with Chrome:\n\n{exc}")
        return

    # A dialog that stays up while we download, closed by us when done.
    waiting = None
    if missing_tools():
        waiting = subprocess.Popen(
            ["osascript", "-e", "activate", "-e",
             f'display dialog "Downloading yt-dlp, FFmpeg and Deno…\\n\\nThis usually takes about a minute. '
             f'This message closes by itself." with title "{APP_NAME}" buttons {{"Hide"}} '
             f'default button "Hide" with icon note giving up after 900'],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        failures = install_tools_cli(verbose=False)
    finally:
        if waiting and waiting.poll() is None:
            waiting.terminate()
    copy_to_clipboard(str(EXTENSION_DIR))

    if failures:
        note = ("\n\nSome parts didn't download (" + ", ".join(failures) +
                "). They'll be retried automatically on your first download.")
    else:
        note = ""
    message = (
        "The helper is installed." + note + "\n\n"
        "Last step (one time): add the extension to Chrome.\n"
        "1. In Chrome, go to chrome://extensions\n"
        "2. Turn on “Developer mode” (top right).\n"
        "3. Click “Load unpacked”, press ⌘⇧G, paste with ⌘V, press Return, then click Select.\n\n"
        "The extension folder's location is already on your clipboard."
    )
    if dialog(message, buttons=("Show Extension Folder", "Done"), default="Done") == "Show Extension Folder":
        open_in_finder(EXTENSION_DIR, reveal=True)


WINDOWS_NEXT_STEPS = (
    "YT Downloader is installed.{note}\n\n"
    "Last step (one time): add the extension to Chrome.\n"
    "1. In Chrome, go to chrome://extensions\n"
    "2. Turn on “Developer mode” (top right).\n"
    "3. Click “Load unpacked”. Click the address bar at the top of the window that opens, "
    "press Ctrl+V, press Enter, then click “Select Folder”.\n\n"
    "The extension folder's location is already on your clipboard, and the folder opens "
    "when you click OK.\n\n"
    "Microsoft Edge works the same way: edge://extensions, “Developer mode” is on the left."
)


def show_next_steps(failures: dict | None = None) -> None:
    """Windows: how to add the extension (the installer runs this at the end)."""
    copy_extension()
    copy_to_clipboard(str(EXTENSION_DIR))
    note = ""
    missing = failures if failures is not None else {name: "" for name in missing_tools()}
    if missing:
        note = ("\n\nSome parts didn't download (" + ", ".join(missing) +
                "). They'll be retried automatically on your first download.")
    message_box(WINDOWS_NEXT_STEPS.format(note=note))
    open_in_finder(EXTENSION_DIR, reveal=True)


def windows_setup() -> None:
    """Windows: double-clicking YT Downloader.exe repairs the install."""
    print(f"{APP_NAME} {VERSION}: setting up…", flush=True)
    register()
    print("Registered with Chrome and Edge.", flush=True)
    failures = install_tools_cli(verbose=True)
    show_next_steps(failures)


def print_paths() -> None:
    print(f"support folder:  {SUPPORT_DIR}")
    print(f"tools:           {BIN_DIR}")
    print(f"extension:       {EXTENSION_DIR}")
    print(f"downloads:       {download_dir()}")
    print(f"helper:          {host_executable() if FROZEN else Path(__file__).resolve()}")
    for name in TOOL_ORDER:
        print(f"{name + ':':16} {tool_path(name)}")


# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    args = argv[1:]
    if args and args[0].startswith("chrome-extension://"):
        # Chrome already enforces allowed_origins; check again anyway.
        if args[0].rstrip("/") + "/" != EXTENSION_ORIGIN:
            log(f"refused caller {args[0]}")
            return 1
        stdin, stdout = sys.stdin.buffer, sys.stdout.buffer
        sys.stdout = sys.stderr  # a stray print() must never corrupt the protocol
        Host(stdin, stdout).run()
        return 0
    if "--version" in args:
        print(VERSION)
        return 0
    if "--register" in args:
        for folder in register():
            print(f"registered in {folder}")
        print(f"extension copied to {EXTENSION_DIR}")
        return 0
    if "--install-tools" in args:
        failures = install_tools_cli()
        return 1 if REQUIRED_TOOLS & failures.keys() else 0
    if "--selftest" in args:
        return selftest()
    if "--uninstall" in args:
        uninstall()
        print("Removed the Chrome registration and", SUPPORT_DIR)
        return 0
    if "--show-next-steps" in args:
        show_next_steps()
        return 0
    if "--paths" in args:
        print_paths()
        return 0
    if not args or all(a.startswith("-psn_") for a in args):
        if IS_MAC:
            gui_install()
            return 0
        if IS_WIN:
            windows_setup()
            return 0
    print(__doc__)
    return 0 if not args else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))

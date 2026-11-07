# PyInstaller spec for the helper Chrome talks to.
#   macOS:   "YT Downloader.app"                         (windowed .app bundle)
#   Windows: "YT Downloader\YT Downloader.exe" + _internal (console program; Chrome
#            starts it hidden, and the installer wraps the folder in a setup .exe)
# Build:  pyinstaller --noconfirm --clean YTDownloader.spec
# The GitHub Actions workflow (.github/workflows/chrome-app-build.yml) does this for you.
import re
import sys
from pathlib import Path

HERE = Path(SPECPATH)
APP = HERE.parent
VERSION = re.search(r'^VERSION = "([^"]+)"', (HERE / "ytdl_helper.py").read_text(encoding="utf-8"), re.M).group(1)
MAC = sys.platform == "darwin"
ICNS = HERE / "build" / "AppIcon.icns"  # made by the workflow from chrome-app/assets/icon-1024.png
ICO = APP / "assets" / "icon.ico"

a = Analysis(
    [str(HERE / "ytdl_helper.py")],
    datas=[(str(APP / "chrome-extension"), "chrome-extension")],
    hiddenimports=["certifi"],
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="YT Downloader",
    # Windows: a console program, because Chrome talks to it over stdin/stdout
    # (Chrome starts it without a window). macOS: windowed, to build an .app.
    console=not MAC,
    argv_emulation=False,
    icon=None if MAC else str(ICO),
)
coll = COLLECT(exe, a.binaries, a.datas, name="YT Downloader")

if MAC:
    app = BUNDLE(
        coll,
        name="YT Downloader.app",
        icon=str(ICNS) if ICNS.exists() else None,
        bundle_identifier="com.likelystudying.ytdownloader",
        version=VERSION,
        info_plist={
            "CFBundleDisplayName": "YT Downloader",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "LSMinimumSystemVersion": "12.0",
            "LSUIElement": True,  # no Dock icon: it only shows dialogs, or runs in the background for Chrome
            "NSHumanReadableCopyright": "MIT License",
        },
    )

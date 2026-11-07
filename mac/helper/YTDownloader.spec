# PyInstaller spec for "YT Downloader.app" (the helper Chrome talks to).
# Build on a Mac:  pyinstaller --noconfirm --clean YTDownloader.spec
# The GitHub Actions workflow (.github/workflows/mac-build.yml) does this for you.
import re
from pathlib import Path

HERE = Path(SPECPATH)
MAC = HERE.parent
VERSION = re.search(r'^VERSION = "([^"]+)"', (HERE / "ytdl_helper.py").read_text(), re.M).group(1)
ICON = HERE / "build" / "AppIcon.icns"  # made by the workflow from mac/assets/icon-1024.png

a = Analysis(
    [str(HERE / "ytdl_helper.py")],
    datas=[(str(MAC / "chrome-extension"), "chrome-extension")],
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
    console=False,
    argv_emulation=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="YT Downloader")
app = BUNDLE(
    coll,
    name="YT Downloader.app",
    icon=str(ICON) if ICON.exists() else None,
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

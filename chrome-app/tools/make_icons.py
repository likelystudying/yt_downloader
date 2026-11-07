"""Draw the YT Downloader icon (a down arrow into a tray) at every size we need.

    python3 chrome-app/tools/make_icons.py

Writes the extension icons, chrome-app/assets/icon-1024.png (the build workflow
turns that into the Mac app's .icns) and chrome-app/assets/icon.ico (Windows).
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
S = 1024


def draw() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # macOS-style squircle-ish rounded square with a vertical jade gradient.
    margin, radius = 100, 185
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([margin, margin, S - margin, S - margin], radius, fill=255)
    top, bottom = (52, 168, 124), (22, 102, 76)
    gradient = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(gradient)
    for y in range(S):
        t = y / (S - 1)
        gd.line([(0, y), (S, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,))
    img.paste(gradient, (0, 0), mask)

    white = (255, 255, 255, 255)
    cx = S // 2
    # Arrow shaft and head.
    d.rounded_rectangle([cx - 52, 260, cx + 52, 560], 40, fill=white)
    d.polygon([(cx - 190, 500), (cx + 190, 500), (cx, 700)], fill=white)
    # Tray.
    d.rounded_rectangle([290, 735, 734, 800], 32, fill=white)
    return img


def main() -> None:
    big = draw()
    (ROOT / "assets").mkdir(exist_ok=True)
    big.save(ROOT / "assets" / "icon-1024.png")
    # Windows .exe and installer icon.
    big.save(ROOT / "assets" / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    icons = ROOT / "chrome-extension" / "icons"
    icons.mkdir(parents=True, exist_ok=True)
    for size in (16, 32, 48, 128):
        big.resize((size, size), Image.LANCZOS).save(icons / f"icon{size}.png")
    print("icons written")


if __name__ == "__main__":
    main()

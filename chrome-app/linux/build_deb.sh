#!/bin/sh
# Package the PyInstaller build as a .deb.
#   chrome-app/linux/build_deb.sh <version> [arch]      (run from the repo root,
#   after: cd chrome-app/helper && pyinstaller --noconfirm --clean YTDownloader.spec)
# Output: out/yt-downloader_<version>_<arch>.deb
set -eu
VERSION=$1
ARCH=${2:-amd64}
HERE=chrome-app/linux
PKG=$HERE/build/pkg
DIST=chrome-app/helper/dist/yt-downloader

rm -rf "$PKG"
mkdir -p "$PKG/DEBIAN" "$PKG/opt/yt-downloader" "$PKG/usr/bin" \
         "$PKG/usr/share/applications" "$PKG/usr/share/icons/hicolor/256x256/apps"

cp -a "$DIST/." "$PKG/opt/yt-downloader/"
# The extension lives at a short, stable path users can type in "Load unpacked".
cp -a chrome-app/chrome-extension "$PKG/opt/yt-downloader/chrome-extension"
cat > "$PKG/opt/yt-downloader/native-messaging-host.json" <<JSON
{
  "name": "com.likelystudying.ytdownloader",
  "description": "YT Downloader helper (runs yt-dlp on this computer)",
  "path": "/opt/yt-downloader/yt-downloader",
  "type": "stdio",
  "allowed_origins": ["chrome-extension://dchdeelhpdnkdichogpodkgkhojfehph/"]
}
JSON
ln -s /opt/yt-downloader/yt-downloader "$PKG/usr/bin/yt-downloader"
install -m 644 "$HERE/yt-downloader.desktop" "$PKG/usr/share/applications/yt-downloader.desktop"
install -m 644 chrome-app/assets/icon-256.png "$PKG/usr/share/icons/hicolor/256x256/apps/yt-downloader.png"

SIZE=$(du -sk --exclude=DEBIAN "$PKG" | cut -f1)
sed -e "s/@VERSION@/$VERSION/" -e "s/@ARCH@/$ARCH/" -e "s/@SIZE@/$SIZE/" "$HERE/control.in" > "$PKG/DEBIAN/control"
install -m 755 "$HERE/postinst" "$PKG/DEBIAN/postinst"
install -m 755 "$HERE/prerm" "$PKG/DEBIAN/prerm"
find "$PKG" -type d -exec chmod 755 {} +
chmod -R go-w "$PKG"

mkdir -p out
dpkg-deb --root-owner-group --build "$PKG" "out/yt-downloader_${VERSION}_${ARCH}.deb"
dpkg-deb --info "out/yt-downloader_${VERSION}_${ARCH}.deb"

#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This build script targets macOS."
  exit 1
fi

if [[ "$(uname -m)" != "arm64" ]]; then
  echo "This first package targets Apple Silicon arm64 Macs."
  exit 1
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENDOR_DIR="$ROOT_DIR/vendor/bin/macos-arm64"
LICENSE_DIR="$ROOT_DIR/vendor/licenses"
FFMPEG_URL="${BLINK_FFMPEG_URL:-https://www.osxexperts.net/ffmpeg80arm.zip}"
FFPROBE_URL="${BLINK_FFPROBE_URL:-https://www.osxexperts.net/ffprobe80arm.zip}"

mkdir -p "$VENDOR_DIR" "$LICENSE_DIR"

download_binary() {
  local url="$1"
  local name="$2"
  local target="$VENDOR_DIR/$name"
  local tmp_zip

  if [[ -x "$target" ]]; then
    echo "$name already present at $target"
    return
  fi

  tmp_zip="$(mktemp -t "blink-${name}.XXXXXX.zip")"
  echo "Downloading $name from $url"
  curl -L --fail "$url" -o "$tmp_zip"
  unzip -jo "$tmp_zip" "$name" -d "$VENDOR_DIR"
  rm -f "$tmp_zip"
  chmod +x "$target"
}

download_binary "$FFMPEG_URL" "ffmpeg"
download_binary "$FFPROBE_URL" "ffprobe"
xattr -cr "$VENDOR_DIR" 2>/dev/null || true

cat > "$LICENSE_DIR/FFMPEG-BUNDLE-NOTICE.txt" <<NOTICE
Blink bundles FFmpeg and FFprobe for personal/local macOS app use.

Downloaded from:
- $FFMPEG_URL
- $FFPROBE_URL

The OSXExperts Apple Silicon builds advertise GPL/libx265 support. Keep this
notice with redistributed app bundles, and perform a full license, source-code,
signing, and notarization review before any public distribution.

FFmpeg project: https://ffmpeg.org/
OSXExperts builds: https://www.osxexperts.net/
NOTICE

"$PYTHON_BIN" -m pip install -e ".[macos]"
APP_VERSION="$("$PYTHON_BIN" -c 'from app import __version__; print(__version__)')"

"$PYTHON_BIN" -m PyInstaller \
  --name Blink \
  --windowed \
  --icon "$ROOT_DIR/Blink.icns" \
  --clean \
  --noconfirm \
  --hidden-import webview.platforms.cocoa \
  --collect-submodules uvicorn \
  --collect-submodules httptools \
  --collect-submodules websockets \
  --add-data "app/templates:app/templates" \
  --add-data "app/static:app/static" \
  --add-data "vendor/bin:vendor/bin" \
  --add-data "vendor/licenses:vendor/licenses" \
  launcher.py

if [[ -d "$ROOT_DIR/dist/Blink.app" ]]; then
  # Patch Info.plist: allow WKWebView to load the local HTTP server.
  # Without NSAllowsLocalNetworking, macOS App Transport Security blocks
  # plain-HTTP connections to 127.0.0.1 and causes an ~8-second timeout
  # before the first page renders.
  PLIST="$ROOT_DIR/dist/Blink.app/Contents/Info.plist"
  /usr/libexec/PlistBuddy -c "Add :NSAppTransportSecurity dict" "$PLIST" 2>/dev/null || true
  /usr/libexec/PlistBuddy -c "Add :NSAppTransportSecurity:NSAllowsLocalNetworking bool true" "$PLIST" 2>/dev/null || \
    /usr/libexec/PlistBuddy -c "Set :NSAppTransportSecurity:NSAllowsLocalNetworking true" "$PLIST"
  /usr/libexec/PlistBuddy -c "Add :NSAppTransportSecurity:NSAllowsArbitraryLoads bool true" "$PLIST" 2>/dev/null || \
    /usr/libexec/PlistBuddy -c "Set :NSAppTransportSecurity:NSAllowsArbitraryLoads true" "$PLIST"
  /usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $APP_VERSION" "$PLIST"
  /usr/libexec/PlistBuddy -c "Add :CFBundleVersion string $APP_VERSION" "$PLIST" 2>/dev/null || \
    /usr/libexec/PlistBuddy -c "Set :CFBundleVersion $APP_VERSION" "$PLIST"

  # PyInstaller may preserve Finder metadata from copied Python frameworks.
  # Clear it only from the generated bundle before applying its local signature.
  xattr -cr "$ROOT_DIR/dist/Blink.app" 2>/dev/null || true
  if ! codesign -s - --force --deep --all-architectures "$ROOT_DIR/dist/Blink.app"; then
    echo "Built app, but ad-hoc codesigning failed. It is still an unsigned local build."
  fi
fi

PYTHON_BIN="$PYTHON_BIN" "$ROOT_DIR/scripts/build_macos_dmg.sh"

echo "Built $ROOT_DIR/dist/Blink.app"

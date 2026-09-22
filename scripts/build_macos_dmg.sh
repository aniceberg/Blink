#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This DMG build script targets macOS."
  exit 1
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
APP_PATH="${BLINK_APP_PATH:-$ROOT_DIR/dist/Blink.app}"
APP_VERSION="$("$PYTHON_BIN" -c 'from app import __version__; print(__version__)')"
OUTPUT_PATH="${BLINK_DMG_OUTPUT:-$ROOT_DIR/dist/Blink v${APP_VERSION}.dmg}"
TEMPLATE_PATH="${BLINK_DMG_TEMPLATE:-}"

if [[ ! -d "$APP_PATH" ]]; then
  echo "Blink.app was not found at $APP_PATH"
  exit 1
fi

BUNDLE_VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP_PATH/Contents/Info.plist")"
if [[ "$BUNDLE_VERSION" != "$APP_VERSION" ]]; then
  echo "Blink.app reports version $BUNDLE_VERSION, expected $APP_VERSION"
  exit 1
fi

if [[ -z "$TEMPLATE_PATH" ]]; then
  latest_template=""
  for candidate in "$ROOT_DIR"/dist/Blink*.dmg; do
    [[ -f "$candidate" ]] || continue
    if [[ -z "$latest_template" || "$candidate" -nt "$latest_template" ]]; then
      latest_template="$candidate"
    fi
  done
  TEMPLATE_PATH="$latest_template"
fi

mkdir -p "$(dirname "$OUTPUT_PATH")"
WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/blink-dmg.XXXXXX")"
RW_BASE="$WORK_DIR/Blink-template"
RW_IMAGE="$RW_BASE.dmg"
MOUNT_POINT=""

cleanup() {
  if [[ -n "$MOUNT_POINT" ]]; then
    hdiutil detach "$MOUNT_POINT" -force >/dev/null 2>&1 || true
  fi
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

if [[ -n "$TEMPLATE_PATH" ]]; then
  if [[ ! -f "$TEMPLATE_PATH" ]]; then
    echo "DMG template was not found at $TEMPLATE_PATH"
    exit 1
  fi

  hdiutil convert "$TEMPLATE_PATH" -format UDRW -o "$RW_BASE" >/dev/null
  MOUNT_POINT="$(hdiutil attach -nobrowse "$RW_IMAGE" | awk '/\/Volumes\// {print $NF; exit}')"
  if [[ -z "$MOUNT_POINT" || ! -d "$MOUNT_POINT" ]]; then
    echo "Could not mount the writable DMG template."
    exit 1
  fi

  rm -rf "$MOUNT_POINT/Blink.app"
  ditto "$APP_PATH" "$MOUNT_POINT/Blink.app"
  hdiutil detach "$MOUNT_POINT" >/dev/null
  MOUNT_POINT=""
  hdiutil convert "$RW_IMAGE" -format ULMO -o "$OUTPUT_PATH" -ov >/dev/null
else
  STAGING_DIR="$WORK_DIR/staging"
  mkdir -p "$STAGING_DIR"
  ditto "$APP_PATH" "$STAGING_DIR/Blink.app"
  ln -s /Applications "$STAGING_DIR/Applications"
  hdiutil create -volname Blink -srcfolder "$STAGING_DIR" -format ULMO -ov "$OUTPUT_PATH" >/dev/null
fi

VERIFY_MOUNT="$(hdiutil attach -readonly -nobrowse "$OUTPUT_PATH" | awk '/\/Volumes\// {print $NF; exit}')"
if [[ -z "$VERIFY_MOUNT" || ! -d "$VERIFY_MOUNT/Blink.app" ]]; then
  echo "The generated DMG does not contain Blink.app."
  exit 1
fi

VERIFY_VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$VERIFY_MOUNT/Blink.app/Contents/Info.plist")"
hdiutil detach "$VERIFY_MOUNT" >/dev/null
if [[ "$VERIFY_VERSION" != "$APP_VERSION" ]]; then
  echo "The generated DMG reports version $VERIFY_VERSION, expected $APP_VERSION"
  exit 1
fi

echo "Built $OUTPUT_PATH"

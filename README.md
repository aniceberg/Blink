# Blink

Blink is a local FastAPI application for creating historical timelapses from UniFi Protect cameras.

It discovers cameras, creates durable timelapse jobs, samples historical footage by timestamp or exported chunks, and assembles MP4/HEVC output with FFmpeg.

On Apple Silicon Macs, Blink defaults to FFmpeg's `hevc_videotoolbox` encoder so native macOS runs can use Apple's hardware HEVC path. On Linux/Docker, use the `libx265` encoder profile.

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`.

Configure the completed videos directory on the Setup page. Absolute paths, `~`, and paths relative to this project are supported; each completed job writes to a `job_ID` folder in that directory.

The host should normally be the UniFi OS console, for example `https://192.168.1.1`. Blink uses:

- Official integration endpoints under `/proxy/protect/integration/v1` for camera discovery.
- Protect API-compatible historical media endpoints under `/proxy/protect/api` for timestamp snapshots and video export.

Historical APIs are not as stable as the official integration API, so Blink records exact failures in each job log and keeps frame manifests for troubleshooting.

## Apple Silicon HEVC

Blink first looks for bundled FFmpeg binaries in `vendor/bin/macos-arm64/`, then falls back to `ffmpeg` and `ffprobe` on `PATH`.

For native macOS runs, confirm FFmpeg exposes VideoToolbox:

```bash
ffmpeg -hide_banner -encoders | grep hevc_videotoolbox
```

Blink's default encoder is `Apple VideoToolbox`, which emits commands shaped like:

```bash
ffmpeg -framerate 30 -i frame_%08d.jpg \
  -c:v hevc_videotoolbox \
  -tag:v hvc1 \
  -pix_fmt yuv420p \
  -q:v 65 \
  -movflags +faststart \
  output.mp4
```

Use the job form's `VideoToolbox quality` field for hardware encode quality. The x265 CRF/preset fields only apply when `libx265` is selected.

Set `BLINK_DEFAULT_ENCODER=libx265` if you want a native run to default back to software x265.

## macOS App Bundle

For a personal unsigned Apple Silicon `.app` bundle:

```bash
scripts/build_macos_app.sh
open dist/Blink.app
```

The build script installs packaging dependencies, downloads Apple Silicon FFmpeg/FFprobe into `vendor/bin/macos-arm64/`, and packages Blink with PyInstaller and pywebview. App data defaults to `~/Library/Application Support/Blink`; completed videos still use the directory configured on the Setup page.

This package is intended for local/personal use and is not signed or notarized. Public distribution needs a signing, notarization, and license-notice review. The bundled OSXExperts FFmpeg build is GPL-oriented when libx265 is enabled; keep the generated notices in `vendor/licenses/` with the app bundle.

## Docker

```bash
docker compose up --build
```

Data is stored in `./data` by default.

Docker on macOS runs Linux containers in a VM and should be treated as the portable `libx265` path, not the Apple VideoToolbox hardware path.

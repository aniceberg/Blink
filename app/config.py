from __future__ import annotations

import os
import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent


def _default_data_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path.home() / "Library" / "Application Support" / "Blink"
    return PROJECT_ROOT / "data"


DATA_DIR = Path(os.environ.get("BLINK_DATA_DIR", _default_data_dir()))
DB_PATH = DATA_DIR / "blink.sqlite3"
MEDIA_DIR = DATA_DIR / "media"
FRAMES_DIR = DATA_DIR / "frames"
EXPORTS_DIR = DATA_DIR / "exports"

DEFAULT_TIMEZONE = "America/New_York"
DEFAULT_SAMPLE_INTERVAL_SECONDS = 60
DEFAULT_OUTPUT_FPS = 30
DEFAULT_DAILY_START = "07:00"
DEFAULT_DAILY_END = "19:00"
DEFAULT_X265_CRF = 28
DEFAULT_X265_PRESET = "medium"
DEFAULT_ENCODER = os.environ.get("BLINK_DEFAULT_ENCODER", "hevc_videotoolbox")
DEFAULT_VIDEOTOOLBOX_QUALITY = 65

SNAPSHOT_STRATEGY_THRESHOLD_SECONDS = 30
VIDEO_EXPORT_CHUNK_SECONDS = 900


def resource_roots() -> list[Path]:
    roots: list[Path] = []
    if getattr(sys, "frozen", False):
        if hasattr(sys, "_MEIPASS"):
            meipass = Path(sys._MEIPASS)  # type: ignore[attr-defined]
            roots.extend([meipass, meipass.parent / "Resources", meipass.parent / "Frameworks"])
        executable = Path(sys.executable).resolve()
        for parent in executable.parents:
            roots.extend([parent, parent / "Resources", parent / "Frameworks"])
    roots.append(PROJECT_ROOT)

    unique: list[Path] = []
    for root in roots:
        if root not in unique:
            unique.append(root)
    return unique


def resource_path(relative: str) -> Path:
    for root in resource_roots():
        candidate = root / relative
        if candidate.exists():
            return candidate
    return PROJECT_ROOT / relative


def ensure_data_dirs() -> None:
    for path in (DATA_DIR, MEDIA_DIR, FRAMES_DIR, EXPORTS_DIR):
        path.mkdir(parents=True, exist_ok=True)

from __future__ import annotations

from pathlib import Path

from app.config import DATA_DIR, MEDIA_DIR, PROJECT_ROOT


def resolve_output_dir(value: str | None) -> Path:
    raw = (value or str(MEDIA_DIR)).strip() or str(MEDIA_DIR)
    path = Path(raw).expanduser()
    if not path.is_absolute():
        if DATA_DIR != PROJECT_ROOT / "data" and raw == "data/media":
            path = MEDIA_DIR
        else:
            path = PROJECT_ROOT / path
    return path.resolve()

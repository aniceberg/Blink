from __future__ import annotations

import shutil
from pathlib import Path

from app.config import DATA_DIR, FRAMES_DIR, MEDIA_DIR, PROJECT_ROOT
from app.utils import inside_directory


def resolve_output_dir(value: str | None) -> Path:
    raw = (value or str(MEDIA_DIR)).strip() or str(MEDIA_DIR)
    path = Path(raw).expanduser()
    if not path.is_absolute():
        if DATA_DIR != PROJECT_ROOT / "data" and raw == "data/media":
            path = MEDIA_DIR
        else:
            path = PROJECT_ROOT / path
    return path.resolve()


def job_frame_cache_dir(job_id: int, frames_dir: Path | None = None) -> Path:
    """Return the only frame-cache directory a job is allowed to remove."""
    if job_id < 1:
        raise ValueError("Job ID must be positive.")
    root = (frames_dir or FRAMES_DIR).resolve()
    path = (root / f"job_{job_id}").resolve()
    if path.parent != root or not inside_directory(path, root):
        raise ValueError("Job frame cache path is outside Blink's frame cache.")
    return path


def delete_job_frame_cache(job_id: int, frames_dir: Path | None = None) -> Path:
    """Delete one job's generated frames, never an arbitrary output directory."""
    path = job_frame_cache_dir(job_id, frames_dir)
    if path.exists():
        shutil.rmtree(path)
    return path

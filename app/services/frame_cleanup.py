from __future__ import annotations

from pathlib import Path

from app.paths import delete_job_frame_cache, job_frame_cache_dir
from app.store import Store


def cleanup_completed_frame_caches(store: Store, frames_dir: Path | None = None) -> list[int]:
    """Remove stale generated frames for completed jobs that did not opt into retention."""
    cleaned: list[int] = []
    for job in store.list_completed_jobs_discarding_frame_cache():
        try:
            path = job_frame_cache_dir(job.id, frames_dir)
            if not path.exists():
                continue
            delete_job_frame_cache(job.id, frames_dir)
            cleaned.append(job.id)
        except (OSError, ValueError):
            # A cleanup failure must not affect durable output or job history.
            continue
    return cleaned

from pathlib import Path

from app.models import JobStatus
from app.services.frame_cleanup import cleanup_completed_frame_caches
from app.store import Store


def _create_job(store: Store, *, keep_intermediate_frames: bool) -> int:
    return store.create_job(
        {
            "camera_ids": ["camera-1"],
            "start_at": None,
            "end_at": None,
            "earliest_available": True,
            "daily_window_enabled": False,
            "daily_start": "00:00:00",
            "daily_end": "23:59:59",
            "sample_interval_seconds": 60,
            "output_fps": 30,
            "encoder": "hevc_videotoolbox",
            "videotoolbox_quality": 65,
            "x265_crf": 28,
            "x265_preset": "medium",
            "output_scale_mode": "original",
            "output_scale_width": None,
            "keep_intermediate_frames": keep_intermediate_frames,
        },
        ["Kitchen"],
    )


def _frame_cache(frames_dir: Path, job_id: int) -> Path:
    path = frames_dir / f"job_{job_id}" / "Kitchen" / "frame.jpg"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"frame")
    return path


def test_startup_cleanup_removes_only_completed_jobs_that_discard_frames(tmp_path):
    store = Store(tmp_path / "blink.sqlite3")
    frames_dir = tmp_path / "frames"
    completed = _create_job(store, keep_intermediate_frames=False)
    retained = _create_job(store, keep_intermediate_frames=True)
    failed = _create_job(store, keep_intermediate_frames=False)
    canceled = _create_job(store, keep_intermediate_frames=False)
    paused = _create_job(store, keep_intermediate_frames=False)
    running = _create_job(store, keep_intermediate_frames=False)
    for job_id in (completed, retained, failed, canceled, paused, running):
        _frame_cache(frames_dir, job_id)

    store.update_job(completed, status=JobStatus.COMPLETED)
    store.update_job(retained, status=JobStatus.COMPLETED)
    store.update_job(failed, status=JobStatus.FAILED)
    store.update_job(canceled, status=JobStatus.CANCELED)
    store.update_job(paused, status=JobStatus.PAUSED)
    store.update_job(running, status=JobStatus.RUNNING)

    cleaned = cleanup_completed_frame_caches(store, frames_dir)

    assert cleaned == [completed]
    assert not (frames_dir / f"job_{completed}").exists()
    for job_id in (retained, failed, canceled, paused, running):
        assert (frames_dir / f"job_{job_id}" / "Kitchen" / "frame.jpg").exists()


def test_startup_cleanup_leaves_unknown_frame_cache_directories_untouched(tmp_path):
    store = Store(tmp_path / "blink.sqlite3")
    frames_dir = tmp_path / "frames"
    unknown = _frame_cache(frames_dir, 999)

    assert cleanup_completed_frame_caches(store, frames_dir) == []
    assert unknown.exists()

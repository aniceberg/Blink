import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app import paths
from app.models import Camera, JobStatus
from app.services.cancel import JobCanceled
from app.services import jobs as jobs_service
from app.store import Store


def _create_job(store: Store, *, keep_intermediate_frames: bool) -> int:
    console_id = store.create_console({"name": "Home", "host": "https://192.168.1.1", "enabled": True})
    console = store.get_console(console_id)
    store.upsert_cameras(
        console,
        [
            Camera(
                camera_id="protect-1",
                console_id=0,
                console_name="",
                protect_camera_id="protect-1",
                name="Kitchen",
                model="G5",
                state="CONNECTED",
                is_connected=True,
                is_recording=True,
                raw={},
            )
        ],
    )
    camera = store.list_cameras()[0]
    timezone = ZoneInfo("America/New_York")
    start = datetime(2026, 5, 1, 12, 0, tzinfo=timezone)
    return store.create_job(
        {
            "camera_ids": [camera.camera_id],
            "start_at": start,
            "end_at": start + timedelta(minutes=1),
            "earliest_available": False,
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
            "frame_repeat": 1,
            "keep_intermediate_frames": keep_intermediate_frames,
        },
        [camera.name],
    )


def _configure_runner(monkeypatch, tmp_path: Path, outcome: str) -> None:
    monkeypatch.setattr(paths, "FRAMES_DIR", tmp_path / "frames")
    monkeypatch.setattr(
        jobs_service,
        "check_ffmpeg_ready",
        lambda: SimpleNamespace(supports=lambda encoder: True, message="ready"),
    )

    class FakeExtractor:
        def __init__(self, store, client):
            self.store = store

        async def extract_for_camera(self, *, job_id, camera, **kwargs):
            frame = paths.FRAMES_DIR / f"job_{job_id}" / "Kitchen" / "frame.jpg"
            frame.parent.mkdir(parents=True, exist_ok=True)
            frame.write_bytes(b"frame")
            if outcome == "canceled":
                raise JobCanceled("Canceled for test")
            if outcome == "paused":
                self.store.pause_job(job_id)
                raise JobCanceled("Paused for test")
            return [frame]

    class FakeAssembler:
        async def assemble(self, *, job_id, output_dir, **kwargs):
            if outcome == "failed":
                raise RuntimeError("Encoder failed for test")
            job_dir = output_dir / f"job_{job_id}"
            job_dir.mkdir(parents=True, exist_ok=True)
            video = job_dir / "timelapse.mp4"
            thumbnail = job_dir / "timelapse.jpg"
            video.write_bytes(b"video")
            thumbnail.write_bytes(b"thumbnail")
            return video, thumbnail

    monkeypatch.setattr(jobs_service, "FrameExtractor", FakeExtractor)
    monkeypatch.setattr(jobs_service, "VideoAssembler", FakeAssembler)


def _run(store: Store, job_id: int) -> None:
    asyncio.run(jobs_service.JobRunner(store).run_job(store.get_job(job_id)))


def test_completed_job_discards_frame_cache_but_keeps_output(monkeypatch, tmp_path):
    store = Store(tmp_path / "blink.sqlite3")
    output_dir = tmp_path / "completed"
    store.save_settings({"timezone": "America/New_York", "output_dir": str(output_dir)})
    job_id = _create_job(store, keep_intermediate_frames=False)
    _configure_runner(monkeypatch, tmp_path, "completed")

    _run(store, job_id)

    job = store.get_job(job_id)
    assert job.status == JobStatus.COMPLETED
    assert not (paths.FRAMES_DIR / f"job_{job_id}").exists()
    assert Path(job.output_path).exists()
    assert Path(job.thumbnail_path).exists()
    assert {artifact["kind"] for artifact in store.list_artifacts(job_id)} == {"video", "thumbnail"}


def test_completed_job_can_retain_frame_cache_for_troubleshooting(monkeypatch, tmp_path):
    store = Store(tmp_path / "blink.sqlite3")
    store.save_settings({"timezone": "America/New_York", "output_dir": str(tmp_path / "completed")})
    job_id = _create_job(store, keep_intermediate_frames=True)
    _configure_runner(monkeypatch, tmp_path, "completed")

    _run(store, job_id)

    assert store.get_job(job_id).status == JobStatus.COMPLETED
    assert (paths.FRAMES_DIR / f"job_{job_id}" / "Kitchen" / "frame.jpg").exists()


@pytest.mark.parametrize(
    ("outcome", "status"),
    [("failed", JobStatus.FAILED), ("canceled", JobStatus.CANCELED), ("paused", JobStatus.PAUSED)],
)
def test_incomplete_job_retains_frame_cache(monkeypatch, tmp_path, outcome, status):
    store = Store(tmp_path / "blink.sqlite3")
    store.save_settings({"timezone": "America/New_York", "output_dir": str(tmp_path / "completed")})
    job_id = _create_job(store, keep_intermediate_frames=False)
    _configure_runner(monkeypatch, tmp_path, outcome)

    _run(store, job_id)

    assert store.get_job(job_id).status == status
    assert (paths.FRAMES_DIR / f"job_{job_id}" / "Kitchen" / "frame.jpg").exists()

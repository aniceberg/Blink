from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from app.config import EXPORTS_DIR, FRAMES_DIR, VIDEO_EXPORT_CHUNK_SECONDS
from app.models import Camera
from app.services.cancel import JobCanceled
from app.services.ffmpeg import build_extract_frames_command, run_ffmpeg
from app.services.timeline import choose_strategy
from app.services.unifi import UniFiClient
from app.store import Store
from app.utils import safe_name


class FrameExtractor:
    def __init__(self, store: Store, client: UniFiClient):
        self.store = store
        self.client = client

    async def extract_for_camera(
        self,
        *,
        job_id: int,
        camera: Camera,
        timestamps: list[datetime],
        sample_interval_seconds: int,
        on_processed: Callable[[int], None] | None = None,
    ) -> list[Path]:
        if not timestamps:
            return []
        strategy = choose_strategy(sample_interval_seconds)
        if strategy == "snapshot":
            return await self._extract_snapshots(job_id, camera, timestamps, on_processed)
        return await self._extract_from_exports(job_id, camera, timestamps, sample_interval_seconds, on_processed)

    async def _extract_snapshots(
        self,
        job_id: int,
        camera: Camera,
        timestamps: list[datetime],
        on_processed: Callable[[int], None] | None,
    ) -> list[Path]:
        frame_paths: list[Path] = []
        camera_dir = FRAMES_DIR / f"job_{job_id}" / safe_name(camera.name)
        for index, timestamp in enumerate(timestamps, start=1):
            if self.store.is_job_canceled(job_id):
                raise JobCanceled("Job canceled.")
            path = camera_dir / f"{index:08d}_{int(timestamp.timestamp())}.jpg"
            try:
                await self.client.download_recording_snapshot(camera.protect_camera_id, timestamp, path)
                self.store.add_frame(job_id, camera.camera_id, timestamp, "success", "snapshot", str(path), None)
                frame_paths.append(path)
            except JobCanceled:
                raise
            except Exception as exc:
                self.store.add_frame(job_id, camera.camera_id, timestamp, "failed", "snapshot", None, str(exc))
            if on_processed:
                on_processed(1)
        return frame_paths

    async def _extract_from_exports(
        self,
        job_id: int,
        camera: Camera,
        timestamps: list[datetime],
        sample_interval_seconds: int,
        on_processed: Callable[[int], None] | None,
    ) -> list[Path]:
        frame_paths: list[Path] = []
        camera_slug = safe_name(camera.name)
        export_dir = EXPORTS_DIR / f"job_{job_id}" / camera_slug
        frame_dir = FRAMES_DIR / f"job_{job_id}" / camera_slug
        export_dir.mkdir(parents=True, exist_ok=True)
        frame_dir.mkdir(parents=True, exist_ok=True)

        start = timestamps[0]
        end = timestamps[-1] + timedelta(seconds=sample_interval_seconds)
        chunk_start = start
        chunk_index = 1

        while chunk_start < end:
            if self.store.is_job_canceled(job_id):
                raise JobCanceled("Job canceled.")
            chunk_end = min(chunk_start + timedelta(seconds=VIDEO_EXPORT_CHUNK_SECONDS), end)
            chunk_timestamps = [ts for ts in timestamps if chunk_start <= ts < chunk_end]
            video_path = export_dir / f"chunk_{chunk_index:04d}.mp4"
            output_pattern = frame_dir / f"chunk_{chunk_index:04d}_%08d.jpg"
            try:
                await self.client.export_video(camera.protect_camera_id, chunk_start, chunk_end, video_path)
                return_code, output = await run_ffmpeg(
                    build_extract_frames_command(video_path, output_pattern, sample_interval_seconds),
                    timeout=None,
                    should_cancel=lambda: self.store.is_job_canceled(job_id),
                )
                if return_code != 0:
                    if return_code == 130:
                        raise JobCanceled("Job canceled.")
                    raise RuntimeError(output)
                extracted = sorted(frame_dir.glob(f"chunk_{chunk_index:04d}_*.jpg"))
                for offset, path in enumerate(extracted):
                    requested = chunk_start + timedelta(seconds=offset * sample_interval_seconds)
                    self.store.add_frame(job_id, camera.camera_id, requested, "success", "export", str(path), None)
                    frame_paths.append(path)
            except JobCanceled:
                raise
            except Exception as exc:
                for requested in chunk_timestamps:
                    self.store.add_frame(job_id, camera.camera_id, requested, "failed", "export", None, str(exc))
            if on_processed and chunk_timestamps:
                on_processed(len(chunk_timestamps))
            chunk_start = chunk_end
            chunk_index += 1
        return sorted(frame_paths)

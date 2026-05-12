from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.config import DEFAULT_ENCODER, DEFAULT_VIDEOTOOLBOX_QUALITY, DEFAULT_X265_CRF, DEFAULT_X265_PRESET
from app.models import Job, JobStatus
from app.paths import resolve_output_dir
from app.services.cancel import JobCanceled
from app.services.extractor import FrameExtractor
from app.services.ffmpeg import check_ffmpeg
from app.services.timeline import TimelinePlanner
from app.services.unifi import UniFiClient
from app.services.video import VideoAssembler
from app.store import Store, utc_now


def describe_output_scale(mode: str, width: int | None) -> str:
    if mode == "original" or not width:
        return "original size"
    return f"{width}px max width"


class JobRunner:
    def __init__(self, store: Store):
        self.store = store
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            job = self.store.next_queued_job()
            if job is None:
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=2)
                except asyncio.TimeoutError:
                    pass
                continue
            await self.run_job(job)

    async def run_job(self, job: Job) -> None:
        def is_canceled() -> bool:
            return self.store.is_job_canceled(job.id)

        def mark_finished(status: JobStatus, message: str, **fields) -> None:
            self.store.update_job(
                job.id,
                status=status,
                message=message,
                finished_at=utc_now(),
                **fields,
            )

        def update_extraction_progress(amount: int) -> None:
            processed, planned = self.store.increment_processed_frame_count(job.id, amount)
            progress = 85 if planned <= 0 else 5 + min(processed / planned, 1) * 80
            self.store.update_job(
                job.id,
                progress=progress,
                message=f"Processed {processed:,} of {planned:,} requested frame timestamps",
            )

        ffmpeg = check_ffmpeg()
        encoder = job.encoder or DEFAULT_ENCODER
        if not ffmpeg.supports(encoder):
            self.store.update_job(
                job.id,
                status=JobStatus.FAILED,
                progress=0,
                message="Setup error",
                error=f"{encoder} is not available. {ffmpeg.message}",
                finished_at=utc_now(),
            )
            return

        self.store.update_job(
            job.id,
            status=JobStatus.RUNNING,
            progress=1,
            message="Preparing job",
            error=None,
            started_at=utc_now(),
            finished_at=None,
            planned_frame_count=0,
            processed_frame_count=0,
        )
        try:
            settings = self.store.get_settings()
            cameras = self.store.get_cameras_by_ids(job.camera_ids)
            if not cameras:
                raise RuntimeError("No selected cameras are available. Refresh cameras and retry.")
            consoles = {camera.console_id: self.store.get_console(camera.console_id) for camera in cameras}
            missing = [camera.console_name for camera in cameras if consoles.get(camera.console_id) is None]
            disabled = [console.name for console in consoles.values() if console and not console.enabled]
            if missing:
                raise RuntimeError(f"Selected cameras reference missing consoles: {', '.join(sorted(set(missing)))}.")
            if disabled:
                raise RuntimeError(f"Selected cameras belong to disabled consoles: {', '.join(sorted(set(disabled)))}.")
            clients = {console_id: UniFiClient(console) for console_id, console in consoles.items() if console is not None}

            tz = ZoneInfo(settings.timezone)
            end_at = job.end_at or datetime.now(tz)
            start_at = job.start_at
            if job.earliest_available or start_at is None:
                starts = [await clients[camera.console_id].earliest_available(camera, end_at) for camera in cameras]
                start_at = min(starts)

            self.store.update_job(
                job.id,
                resolved_start_at=start_at.isoformat(),
                resolved_end_at=end_at.isoformat(),
            )

            planner = TimelinePlanner(settings.timezone)
            timestamps = planner.expand(
                start_at=start_at,
                end_at=end_at,
                daily_start=job.daily_start,
                daily_end=job.daily_end,
                interval_seconds=job.sample_interval_seconds,
            )
            if not timestamps:
                raise RuntimeError("The selected range and daily window produced no frame timestamps.")

            planned_total = len(timestamps) * len(cameras)
            self.store.update_job(
                job.id,
                progress=5,
                planned_frame_count=planned_total,
                processed_frame_count=0,
                message=f"Planned {len(timestamps):,} timestamps per camera",
            )

            all_frames: list[Path] = []
            total_cameras = len(cameras)
            for index, camera in enumerate(cameras, start=1):
                current = self.store.get_job(job.id)
                if current and current.status == JobStatus.CANCELED:
                    raise JobCanceled("Job canceled.")
                self.store.update_job(job.id, progress=5 + (index - 1) * 70 / total_cameras, message=f"Extracting frames for {camera.name}")
                extractor = FrameExtractor(self.store, clients[camera.console_id])
                frames = await extractor.extract_for_camera(
                    job_id=job.id,
                    camera=camera,
                    timestamps=timestamps,
                    sample_interval_seconds=job.sample_interval_seconds,
                    on_processed=update_extraction_progress,
                )
                all_frames.extend(frames)

            if not all_frames:
                raise RuntimeError("No frames were extracted. Check job logs for UniFi API errors or recording gaps.")

            self.store.update_job(job.id, progress=85, message=f"Encoding {len(all_frames):,} frames with {encoder}")
            video_path, thumbnail_path = await VideoAssembler().assemble(
                job_id=job.id,
                frame_paths=sorted(all_frames),
                fps=job.output_fps,
                encoder=encoder,
                videotoolbox_quality=job.videotoolbox_quality or DEFAULT_VIDEOTOOLBOX_QUALITY,
                x265_crf=job.x265_crf or DEFAULT_X265_CRF,
                x265_preset=job.x265_preset or DEFAULT_X265_PRESET,
                scale_max_width=job.output_scale_width,
                output_dir=resolve_output_dir(settings.output_dir),
                metadata=self._video_metadata(job, start_at, end_at),
                should_cancel=is_canceled,
            )
            self.store.update_job(job.id, progress=98, message="Finalizing output")
            self.store.add_artifact(
                job.id,
                "video",
                str(video_path),
                {
                    "codec": encoder,
                    "fps": job.output_fps,
                    "output_scale": describe_output_scale(job.output_scale_mode, job.output_scale_width),
                },
            )
            if thumbnail_path:
                self.store.add_artifact(job.id, "thumbnail", str(thumbnail_path))
            self.store.update_job(
                job.id,
                status=JobStatus.COMPLETED,
                progress=100,
                message="Completed",
                output_path=str(video_path),
                thumbnail_path=str(thumbnail_path) if thumbnail_path else None,
                error=None,
                finished_at=utc_now(),
            )
        except JobCanceled:
            mark_finished(JobStatus.CANCELED, "Canceled", error=None)
        except Exception as exc:
            if self.store.is_job_canceled(job.id):
                mark_finished(JobStatus.CANCELED, "Canceled", error=None)
                return
            mark_finished(JobStatus.FAILED, "Failed", error=str(exc))

    def _video_metadata(self, job: Job, start_at: datetime, end_at: datetime) -> dict[str, str]:
        daily_window = f"{job.daily_start}-{job.daily_end}" if job.daily_window_enabled else "full day"
        output_scale = describe_output_scale(job.output_scale_mode, job.output_scale_width)
        return {
            "title": f"Blink Timelapse Job #{job.id}",
            "comment": f"Source range: {start_at.isoformat()} to {end_at.isoformat()}; daily window: {daily_window}; output scale: {output_scale}",
            "creation_time": job.created_at.isoformat(),
            "source_start": start_at.isoformat(),
            "source_end": end_at.isoformat(),
            "camera_names": ", ".join(job.camera_names),
            "output_scale": output_scale,
        }

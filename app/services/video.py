from __future__ import annotations

from pathlib import Path
from typing import Callable

from app.services.cancel import JobCanceled
from app.services.ffmpeg import build_hevc_command, build_thumbnail_command, run_ffmpeg


class VideoAssembler:
    async def assemble(
        self,
        *,
        job_id: int,
        frame_paths: list[Path],
        fps: int,
        encoder: str,
        videotoolbox_quality: int,
        x265_crf: int,
        x265_preset: str,
        output_dir: Path,
        scale_max_width: int | None = None,
        metadata: dict[str, str] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> tuple[Path, Path | None]:
        if not frame_paths:
            raise ValueError("No frames were captured for this timelapse.")
        if should_cancel and should_cancel():
            raise JobCanceled("Job canceled.")

        job_dir = output_dir / f"job_{job_id}"
        job_dir.mkdir(parents=True, exist_ok=True)
        output_path = job_dir / f"timelapse_job_{job_id}.mp4"
        thumbnail_path = job_dir / f"timelapse_job_{job_id}.jpg"
        frame_list_path = job_dir / f"timelapse_job_{job_id}_frames.txt"
        duration = 1 / fps

        try:
            self._write_concat_file(frame_list_path, frame_paths, duration, should_cancel)
            command = build_hevc_command(
                frame_list_path,
                output_path,
                fps=fps,
                encoder=encoder,
                videotoolbox_quality=videotoolbox_quality,
                x265_crf=x265_crf,
                x265_preset=x265_preset,
                metadata=metadata,
                input_mode="concat",
                scale_max_width=scale_max_width,
            )
            return_code, output = await run_ffmpeg(command, timeout=None, should_cancel=should_cancel)
            if return_code != 0:
                if return_code == 130:
                    raise JobCanceled("Job canceled.")
                raise RuntimeError(f"FFmpeg HEVC encode failed: {output}")

            if should_cancel and should_cancel():
                raise JobCanceled("Job canceled.")
            thumb_return, _ = await run_ffmpeg(build_thumbnail_command(output_path, thumbnail_path), timeout=30, should_cancel=should_cancel)
            return output_path, thumbnail_path if thumb_return == 0 and thumbnail_path.exists() else None
        finally:
            frame_list_path.unlink(missing_ok=True)

    def _write_concat_file(
        self,
        path: Path,
        frame_paths: list[Path],
        duration: float,
        should_cancel: Callable[[], bool] | None,
    ) -> None:
        lines: list[str] = ["ffconcat version 1.0"]
        for source in frame_paths:
            if should_cancel and should_cancel():
                raise JobCanceled("Job canceled.")
            escaped = str(source.resolve()).replace("'", "'\\''")
            lines.append(f"file '{escaped}'")
            lines.append(f"duration {duration:.8f}")
        escaped_last = str(frame_paths[-1].resolve()).replace("'", "'\\''")
        lines.append(f"file '{escaped_last}'")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

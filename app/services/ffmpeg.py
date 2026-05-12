from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Callable

from app.config import resource_roots


@dataclass(frozen=True)
class FFmpegPaths:
    ffmpeg_path: str | None
    ffprobe_path: str | None
    source: str


@dataclass(frozen=True)
class FFmpegStatus:
    ffmpeg_path: str | None
    ffprobe_path: str | None
    source: str
    has_libx265: bool
    has_hevc_videotoolbox: bool
    message: str

    @property
    def ok(self) -> bool:
        return self.ffmpeg_path is not None and (self.has_hevc_videotoolbox or self.has_libx265)

    def supports(self, encoder: str) -> bool:
        if encoder == "hevc_videotoolbox":
            return self.ffmpeg_path is not None and self.has_hevc_videotoolbox
        if encoder == "libx265":
            return self.ffmpeg_path is not None and self.has_libx265
        return False


def _bundled_bin_dirs() -> list[Path]:
    return [root / "vendor" / "bin" / "macos-arm64" for root in resource_roots()]


def resolve_ffmpeg_paths(vendor_bin_dir: Path | None = None) -> FFmpegPaths:
    env_ffmpeg = os.environ.get("BLINK_FFMPEG_PATH")
    env_ffprobe = os.environ.get("BLINK_FFPROBE_PATH")
    if env_ffmpeg:
        return FFmpegPaths(env_ffmpeg, env_ffprobe or shutil.which("ffprobe"), "override")

    bin_dirs = [vendor_bin_dir] if vendor_bin_dir else _bundled_bin_dirs()
    for bin_dir in bin_dirs:
        if not bin_dir:
            continue
        bundled_ffmpeg = bin_dir / "ffmpeg"
        bundled_ffprobe = bin_dir / "ffprobe"
        if bundled_ffmpeg.exists() and bundled_ffprobe.exists():
            return FFmpegPaths(str(bundled_ffmpeg), str(bundled_ffprobe), "bundled")

    return FFmpegPaths(shutil.which("ffmpeg"), shutil.which("ffprobe"), "external")


def ffmpeg_command() -> str:
    paths = resolve_ffmpeg_paths()
    if paths.source in {"bundled", "override"} and paths.ffmpeg_path:
        return paths.ffmpeg_path
    return "ffmpeg"


def check_ffmpeg() -> FFmpegStatus:
    paths = resolve_ffmpeg_paths()
    ffmpeg_path = paths.ffmpeg_path
    ffprobe_path = paths.ffprobe_path
    if not ffmpeg_path:
        return FFmpegStatus(None, ffprobe_path, paths.source, False, False, "FFmpeg is not installed or bundled.")

    try:
        result = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        return FFmpegStatus(ffmpeg_path, ffprobe_path, paths.source, False, False, f"Could not inspect FFmpeg encoders: {exc}")

    encoders = f"{result.stdout}\n{result.stderr}"
    has_libx265 = "libx265" in encoders
    has_hevc_videotoolbox = "hevc_videotoolbox" in encoders
    source_label = "bundled" if paths.source == "bundled" else "external"
    if has_hevc_videotoolbox:
        return FFmpegStatus(ffmpeg_path, ffprobe_path, paths.source, has_libx265, True, f"{source_label.title()} FFmpeg with Apple VideoToolbox HEVC is available.")
    if has_libx265:
        return FFmpegStatus(ffmpeg_path, ffprobe_path, paths.source, True, False, f"{source_label.title()} FFmpeg with libx265 is available. Apple VideoToolbox HEVC is not available in this runtime.")
    return FFmpegStatus(ffmpeg_path, ffprobe_path, paths.source, False, False, "FFmpeg is available, but no HEVC encoder was found.")


def _decode_output(stdout: bytes | None, stderr: bytes | None) -> str:
    return "\n".join(part.decode("utf-8", errors="ignore") for part in (stdout, stderr) if part)


async def run_ffmpeg(
    command: list[str],
    timeout: int | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> tuple[int, str]:
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    started_at = monotonic()
    communicate_task = asyncio.create_task(process.communicate())
    while True:
        if should_cancel and should_cancel():
            process.terminate()
            try:
                stdout, stderr = await asyncio.wait_for(asyncio.shield(communicate_task), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
                stdout, stderr = await communicate_task
            return 130, f"FFmpeg canceled.\n{_decode_output(stdout, stderr)}".strip()

        remaining = 1.0
        if timeout is not None:
            remaining = min(remaining, max(timeout - (monotonic() - started_at), 0.0))
            if remaining <= 0:
                process.kill()
                await communicate_task
                return 124, "FFmpeg timed out."

        try:
            stdout, stderr = await asyncio.wait_for(asyncio.shield(communicate_task), timeout=remaining)
            return process.returncode or 0, _decode_output(stdout, stderr)
        except asyncio.TimeoutError:
            continue


def metadata_args(metadata: dict[str, str] | None) -> list[str]:
    args: list[str] = []
    for key, value in (metadata or {}).items():
        if value:
            args.extend(["-metadata", f"{key}={value}"])
    return args


def input_args(frame_input: Path, fps: int, input_mode: str) -> list[str]:
    if input_mode == "concat":
        return [
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(frame_input),
            "-r",
            str(fps),
        ]
    return [
        "-framerate",
        str(fps),
        "-i",
        str(frame_input),
    ]


def build_scale_filter(max_width: int | None) -> str | None:
    if not max_width:
        return None
    if max_width < 2:
        raise ValueError("Scale max width must be at least 2 pixels.")
    return f"scale=w='trunc(min(iw\\,{max_width})/2)*2':h=-2"


def filter_args(scale_max_width: int | None) -> list[str]:
    scale_filter = build_scale_filter(scale_max_width)
    return ["-vf", scale_filter] if scale_filter else []


def build_x265_command(
    frame_pattern: Path,
    output_path: Path,
    fps: int,
    crf: int,
    preset: str,
    metadata: dict[str, str] | None = None,
    input_mode: str = "image2",
    scale_max_width: int | None = None,
) -> list[str]:
    return [
        ffmpeg_command(),
        "-hide_banner",
        "-loglevel",
        "error",
        *input_args(frame_pattern, fps, input_mode),
        *filter_args(scale_max_width),
        "-c:v",
        "libx265",
        "-tag:v",
        "hvc1",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        str(crf),
        "-preset",
        preset,
        *metadata_args(metadata),
        "-movflags",
        "+faststart",
        "-y",
        str(output_path),
    ]


def build_videotoolbox_command(
    frame_pattern: Path,
    output_path: Path,
    fps: int,
    quality: int,
    metadata: dict[str, str] | None = None,
    input_mode: str = "image2",
    scale_max_width: int | None = None,
) -> list[str]:
    return [
        ffmpeg_command(),
        "-hide_banner",
        "-loglevel",
        "error",
        *input_args(frame_pattern, fps, input_mode),
        *filter_args(scale_max_width),
        "-c:v",
        "hevc_videotoolbox",
        "-tag:v",
        "hvc1",
        "-pix_fmt",
        "yuv420p",
        "-q:v",
        str(quality),
        *metadata_args(metadata),
        "-movflags",
        "+faststart",
        "-y",
        str(output_path),
    ]


def build_hevc_command(
    frame_pattern: Path,
    output_path: Path,
    *,
    fps: int,
    encoder: str,
    videotoolbox_quality: int,
    x265_crf: int,
    x265_preset: str,
    metadata: dict[str, str] | None = None,
    input_mode: str = "image2",
    scale_max_width: int | None = None,
) -> list[str]:
    if encoder == "hevc_videotoolbox":
        return build_videotoolbox_command(frame_pattern, output_path, fps, videotoolbox_quality, metadata, input_mode, scale_max_width)
    if encoder == "libx265":
        return build_x265_command(frame_pattern, output_path, fps, x265_crf, x265_preset, metadata, input_mode, scale_max_width)
    raise ValueError(f"Unsupported HEVC encoder: {encoder}")


def build_extract_frames_command(video_path: Path, output_pattern: Path, sample_interval_seconds: int) -> list[str]:
    return [
        ffmpeg_command(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video_path),
        "-vf",
        f"fps=1/{sample_interval_seconds}",
        "-q:v",
        "2",
        "-y",
        str(output_pattern),
    ]


def build_thumbnail_command(video_path: Path, thumbnail_path: Path) -> list[str]:
    return [
        ffmpeg_command(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        "00:00:01",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-q:v",
        "3",
        "-y",
        str(thumbnail_path),
    ]

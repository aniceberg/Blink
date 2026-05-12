from pathlib import Path

from app.services.ffmpeg import (
    build_hevc_command,
    build_scale_filter,
    build_videotoolbox_command,
    build_x265_command,
    resolve_ffmpeg_paths,
)


def test_x265_command_uses_hevc_defaults():
    command = build_x265_command(Path("frames/frame_%08d.jpg"), Path("out.mp4"), 30, 28, "medium")
    assert "-c:v" in command
    assert "libx265" in command
    assert "-tag:v" in command
    assert "hvc1" in command
    assert "-pix_fmt" in command
    assert "yuv420p" in command


def test_videotoolbox_command_uses_apple_hevc_encoder():
    command = build_videotoolbox_command(Path("frames/frame_%08d.jpg"), Path("out.mp4"), 30, 65)
    assert "-c:v" in command
    assert "hevc_videotoolbox" in command
    assert "-tag:v" in command
    assert "hvc1" in command
    assert "-q:v" in command
    assert "65" in command


def test_hevc_command_selects_encoder_profile():
    vt = build_hevc_command(
        Path("frames/frame_%08d.jpg"),
        Path("out.mp4"),
        fps=24,
        encoder="hevc_videotoolbox",
        videotoolbox_quality=70,
        x265_crf=28,
        x265_preset="medium",
    )
    x265 = build_hevc_command(
        Path("frames/frame_%08d.jpg"),
        Path("out.mp4"),
        fps=24,
        encoder="libx265",
        videotoolbox_quality=70,
        x265_crf=28,
        x265_preset="medium",
    )
    assert "hevc_videotoolbox" in vt
    assert "libx265" in x265


def test_hevc_command_supports_concat_input_and_metadata():
    command = build_hevc_command(
        Path("frames.txt"),
        Path("out.mp4"),
        fps=30,
        encoder="libx265",
        videotoolbox_quality=70,
        x265_crf=28,
        x265_preset="medium",
        metadata={"source_start": "2026-04-09T00:00:00-04:00", "camera_names": "Front NE"},
        input_mode="concat",
    )
    assert Path(command[0]).name == "ffmpeg"
    assert command[1:8] == ["-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0"]
    assert "-metadata" in command
    assert "source_start=2026-04-09T00:00:00-04:00" in command
    assert "camera_names=Front NE" in command


def test_scale_filter_caps_width_without_upscaling_and_preserves_aspect():
    assert build_scale_filter(None) is None
    assert build_scale_filter(1920) == "scale=w='trunc(min(iw\\,1920)/2)*2':h=-2"


def test_hevc_command_includes_scale_filter_when_requested():
    command = build_hevc_command(
        Path("frames.txt"),
        Path("out.mp4"),
        fps=30,
        encoder="libx265",
        videotoolbox_quality=70,
        x265_crf=28,
        x265_preset="medium",
        input_mode="concat",
        scale_max_width=1280,
    )
    assert "-vf" in command
    assert "scale=w='trunc(min(iw\\,1280)/2)*2':h=-2" in command


def test_ffmpeg_resolver_prefers_bundled_binaries(tmp_path):
    bin_dir = tmp_path / "vendor" / "bin" / "macos-arm64"
    bin_dir.mkdir(parents=True)
    ffmpeg = bin_dir / "ffmpeg"
    ffprobe = bin_dir / "ffprobe"
    ffmpeg.write_text("#!/bin/sh\n", encoding="utf-8")
    ffprobe.write_text("#!/bin/sh\n", encoding="utf-8")

    paths = resolve_ffmpeg_paths(bin_dir)

    assert paths.source == "bundled"
    assert paths.ffmpeg_path == str(ffmpeg)
    assert paths.ffprobe_path == str(ffprobe)

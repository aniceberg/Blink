from pathlib import Path

from app.config import MEDIA_DIR, PROJECT_ROOT
from app.paths import delete_job_frame_cache, job_frame_cache_dir, resolve_output_dir


def test_output_dir_defaults_to_media_dir():
    assert resolve_output_dir(None) == MEDIA_DIR.resolve()
    assert resolve_output_dir("") == MEDIA_DIR.resolve()


def test_output_dir_resolves_relative_to_project_root():
    assert resolve_output_dir("exports/timelapses") == (PROJECT_ROOT / "exports/timelapses").resolve()


def test_output_dir_preserves_absolute_path(tmp_path):
    assert resolve_output_dir(str(tmp_path)) == tmp_path.resolve()


def test_output_dir_expands_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert resolve_output_dir("~/Blink Videos") == (tmp_path / "Blink Videos").resolve()


def test_job_frame_cache_cleanup_is_scoped_to_one_job_directory(tmp_path):
    frames_dir = tmp_path / "frames"
    target = frames_dir / "job_42"
    other_job = frames_dir / "job_43"
    target.mkdir(parents=True)
    other_job.mkdir(parents=True)
    (target / "frame.jpg").write_bytes(b"frame")
    (other_job / "frame.jpg").write_bytes(b"frame")

    deleted = delete_job_frame_cache(42, frames_dir)

    assert deleted == target.resolve()
    assert not target.exists()
    assert other_job.exists()
    assert job_frame_cache_dir(42, frames_dir) == target.resolve()

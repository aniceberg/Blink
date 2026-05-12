from pathlib import Path

from app.config import MEDIA_DIR, PROJECT_ROOT
from app.paths import resolve_output_dir


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

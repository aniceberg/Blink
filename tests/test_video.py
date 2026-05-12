from pathlib import Path

from app.services.video import VideoAssembler


def test_concat_file_lists_frames_without_sequence_copy(tmp_path):
    frames = []
    for index in range(2):
        path = tmp_path / f"frame_{index}.jpg"
        path.write_bytes(b"jpeg")
        frames.append(path)

    list_path = tmp_path / "frames.txt"
    VideoAssembler()._write_concat_file(list_path, frames, 1 / 30, None)

    content = list_path.read_text()
    assert "ffconcat version 1.0" in content
    assert str(frames[0].resolve()) in content
    assert "duration 0.03333333" in content
    assert "frame_%08d" not in content
    assert not (tmp_path / "sequence").exists()

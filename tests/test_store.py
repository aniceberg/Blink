import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from app.models import Camera
from app.store import Store


def test_store_persists_new_job_progress_and_timing_fields(tmp_path):
    store = Store(tmp_path / "blink.sqlite3")
    tz = ZoneInfo("America/New_York")
    job_id = store.create_job(
        {
            "camera_ids": ["camera-1"],
            "start_at": datetime(2026, 4, 9, 0, 0, tzinfo=tz),
            "end_at": datetime(2026, 4, 9, 23, 59, 59, tzinfo=tz),
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
            "output_scale_mode": "max_1920",
            "output_scale_width": 1920,
        },
        ["Front NE"],
    )

    store.update_job(job_id, planned_frame_count=10, started_at="2026-05-10T14:00:00+00:00")
    processed, planned = store.increment_processed_frame_count(job_id, 3)
    job = store.get_job(job_id)

    assert processed == 3
    assert planned == 10
    assert job.daily_window_enabled is False
    assert job.output_scale_mode == "max_1920"
    assert job.output_scale_width == 1920
    assert job.processed_frame_count == 3
    assert job.started_at.isoformat() == "2026-05-10T14:00:00+00:00"


def test_existing_single_console_settings_migrate_to_console(tmp_path):
    db_path = tmp_path / "blink.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            host TEXT NOT NULL DEFAULT '',
            api_key TEXT NOT NULL DEFAULT '',
            username TEXT,
            password TEXT,
            verify_ssl INTEGER NOT NULL DEFAULT 0,
            timezone TEXT NOT NULL DEFAULT 'America/New_York',
            output_dir TEXT NOT NULL DEFAULT 'data/media',
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO settings (id, host, api_key, username, password, verify_ssl, timezone, output_dir, updated_at) VALUES (1, ?, ?, ?, ?, 0, ?, ?, ?)",
        ("https://192.168.1.1", "key", "user", "pass", "America/New_York", "data/media", "2026-05-10T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()

    store = Store(db_path)
    console = store.list_consoles()[0]

    assert console.host == "https://192.168.1.1"
    assert console.api_key == "key"
    assert console.username == "user"
    assert console.name == "192.168.1.1"


def test_store_persists_consoles_and_camera_console_metadata(tmp_path):
    store = Store(tmp_path / "blink.sqlite3")
    console_id = store.create_console(
        {
            "name": "House",
            "host": "https://192.168.1.1",
            "api_key": "key",
            "username": "user",
            "password": "pass",
            "verify_ssl": False,
            "enabled": True,
        }
    )
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

    assert console.name == "House"
    assert camera.camera_id == f"c{console_id}:protect-1"
    assert camera.protect_camera_id == "protect-1"
    assert camera.console_id == console_id
    assert camera.console_name == "House"


def test_disabled_consoles_are_excluded_from_active_camera_lists(tmp_path):
    store = Store(tmp_path / "blink.sqlite3")
    console_id = store.create_console({"name": "Disabled", "host": "https://10.0.0.1", "enabled": False})
    console = store.get_console(console_id)
    store.upsert_cameras(
        console,
        [
            Camera(
                camera_id="protect-2",
                console_id=0,
                console_name="",
                protect_camera_id="protect-2",
                name="Driveway",
                model=None,
                state=None,
                is_connected=False,
                is_recording=False,
                raw={},
            )
        ],
    )

    assert len(store.list_cameras()) == 1
    assert store.list_cameras(enabled_consoles_only=True) == []

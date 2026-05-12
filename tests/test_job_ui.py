from fastapi.testclient import TestClient

import app.main as main
from app.models import Camera
from app.store import Store


def test_new_job_daily_window_controls_start_disabled():
    client = TestClient(main.app)
    response = client.get("/jobs/new")

    assert response.status_code == 200
    assert 'name="daily_window_enabled" data-toggle-daily-window' in response.text
    assert 'data-daily-window-fields' in response.text
    assert 'name="daily_start" value="' in response.text
    assert 'step="60" disabled' in response.text
    assert 'name="daily_end" value="' in response.text


def test_new_job_earliest_available_starts_unchecked_with_enabled_start_date():
    client = TestClient(main.app)
    response = client.get("/jobs/new")

    assert response.status_code == 200
    assert 'name="earliest_available" data-toggle-earliest-available' in response.text
    assert 'name="earliest_available" data-toggle-earliest-available checked' not in response.text
    assert 'data-start-date-field' in response.text
    assert 'type="date" name="start_at" disabled' not in response.text


def test_job_status_response_is_not_cached():
    client = TestClient(main.app)
    jobs = main.store.list_jobs()
    if not jobs:
        job_id = main.store.create_job(
            {
                "camera_ids": ["camera-1"],
                "start_at": None,
                "end_at": None,
                "earliest_available": True,
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
            },
            ["Camera 1"],
        )
    else:
        job_id = jobs[0].id

    response = client.get(f"/jobs/{job_id}/status")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "elapsed_seconds" in response.json()


def test_queued_job_status_has_zero_progress_and_no_elapsed():
    client = TestClient(main.app)
    job_id = main.store.create_job(
        {
            "camera_ids": ["camera-1"],
            "start_at": None,
            "end_at": None,
            "earliest_available": True,
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
        },
        ["Camera 1"],
    )
    main.store.update_job(job_id, progress=42)

    response = client.get(f"/jobs/{job_id}/status")
    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "queued"
    assert payload["progress"] == 0
    assert payload["elapsed_seconds"] is None


def test_new_job_output_resolution_controls_default_to_original():
    client = TestClient(main.app)
    response = client.get("/jobs/new")

    assert response.status_code == 200
    assert 'name="output_scale_mode" data-output-scale-mode' in response.text
    assert 'value="original" selected' in response.text
    assert 'name="output_scale_width"' in response.text
    assert 'data-output-scale-custom class="disabled-field"' in response.text


def test_daily_window_rejects_same_day_overnight_window():
    try:
        main.validate_daily_window_range(
            daily_window_enabled=True,
            daily_start="19:00",
            daily_end="05:00",
            earliest_available=False,
            start_at="2026-04-09",
            end_at="2026-04-09",
        )
    except ValueError as exc:
        assert str(exc) == "Overnight daily windows require an end date after the start date."
    else:
        raise AssertionError("Expected overnight same-day validation to fail.")


def test_daily_window_allows_multi_day_overnight_window():
    main.validate_daily_window_range(
        daily_window_enabled=True,
        daily_start="19:00",
        daily_end="05:00",
        earliest_available=False,
        start_at="2026-04-09",
        end_at="2026-04-10",
    )


def test_full_day_mode_ignores_daily_window_times():
    main.validate_daily_window_range(
        daily_window_enabled=False,
        daily_start="19:00",
        daily_end="05:00",
        earliest_available=False,
        start_at="2026-04-09",
        end_at="2026-04-09",
    )


def test_setup_detect_host_endpoint(monkeypatch):
    monkeypatch.setattr(main, "detect_default_gateway", lambda: "192.168.1.1")
    client = TestClient(main.app)

    response = client.get("/setup/detect-host")

    assert response.status_code == 200
    assert response.json() == {"host": "https://192.168.1.1", "gateway": "192.168.1.1"}


def test_setup_page_renders_detect_secret_and_folder_controls():
    client = TestClient(main.app)
    response = client.get("/setup")

    assert response.status_code == 200
    assert "data-detect-host" in response.text
    assert 'name="api_key"' in response.text
    assert 'type="password"' in response.text
    assert "data-toggle-secret" in response.text
    assert "data-choose-output-dir" in response.text


def test_new_job_frame_interval_options_are_sorted_by_frequency():
    client = TestClient(main.app)
    response = client.get("/jobs/new")

    expected = [
        'value="1s"',
        'value="10s"',
        'value="30s"',
        'value="1m" selected',
        'value="5m"',
        'value="15m"',
        'value="30m"',
        'value="1h"',
        'value="3h"',
        'value="6h"',
        'value="12h"',
        'value="24h"',
    ]
    positions = [response.text.index(item) for item in expected]

    assert response.status_code == 200
    assert positions == sorted(positions)


def test_setup_page_renders_console_cards(monkeypatch, tmp_path):
    test_store = Store(tmp_path / "blink.sqlite3")
    test_store.create_console({"name": "House", "host": "https://192.168.1.1", "enabled": True})
    monkeypatch.setattr(main, "store", test_store)
    client = TestClient(main.app)

    response = client.get("/setup")

    assert response.status_code == 200
    assert "UniFi consoles" in response.text
    assert "House" in response.text
    assert 'action="/setup/consoles/' in response.text
    assert "Add console" in response.text


def test_cameras_page_renders_console_filters_and_search(monkeypatch, tmp_path):
    test_store = Store(tmp_path / "blink.sqlite3")
    c1 = test_store.create_console({"name": "House", "host": "https://192.168.1.1", "enabled": True})
    c2 = test_store.create_console({"name": "Barn", "host": "https://192.168.2.1", "enabled": True})
    for console in (test_store.get_console(c1), test_store.get_console(c2)):
        test_store.upsert_cameras(
            console,
            [
                Camera(
                    camera_id=f"{console.id}-kitchen",
                    console_id=0,
                    console_name="",
                    protect_camera_id=f"{console.id}-kitchen",
                    name="Kitchen",
                    model="G5",
                    state="CONNECTED",
                    is_connected=True,
                    is_recording=True,
                    raw={},
                )
            ],
        )
    monkeypatch.setattr(main, "store", test_store)
    client = TestClient(main.app)

    response = client.get("/cameras")

    assert response.status_code == 200
    assert "data-camera-search" in response.text
    assert "data-console-filter" in response.text
    assert "data-camera-item" in response.text
    assert "House" in response.text
    assert "Barn" in response.text

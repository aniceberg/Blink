from app.utils import parse_default_gateway, parse_history_boundary, parse_interval


def test_parse_compact_intervals():
    assert parse_interval("1s") == 1
    assert parse_interval("10s") == 10
    assert parse_interval("30s") == 30
    assert parse_interval("1m") == 60
    assert parse_interval("5m") == 300
    assert parse_interval("1h") == 3600
    assert parse_interval("3h") == 10800
    assert parse_interval("6h") == 21600
    assert parse_interval("12h") == 43200
    assert parse_interval("24h") == 86400


def test_parse_human_intervals():
    assert parse_interval("1 frame per minute") == 60
    assert parse_interval("1 frame per 10 seconds") == 10
    assert parse_interval("2 frames per minute") == 30


def test_parse_history_boundary_uses_daily_window_time():
    start = parse_history_boundary("2026-04-09", "America/New_York", "07:00")
    end = parse_history_boundary("2026-04-09", "America/New_York", "19:00")

    assert start.isoformat() == "2026-04-09T07:00:00-04:00"
    assert end.isoformat() == "2026-04-09T19:00:00-04:00"


def test_parse_history_boundary_supports_full_day_seconds():
    end = parse_history_boundary("2026-04-09", "America/New_York", "23:59:59")
    assert end.isoformat() == "2026-04-09T23:59:59-04:00"


def test_parse_history_boundary_keeps_datetime_for_old_clients():
    dt = parse_history_boundary("2026-04-09T12:30", "America/New_York", "07:00")
    assert dt.isoformat() == "2026-04-09T12:30:00-04:00"


def test_parse_default_gateway_from_macos_route_output():
    output = """
   route to: default
destination: default
       mask: default
    gateway: 192.168.1.1
  interface: en0
"""
    assert parse_default_gateway(output) == "192.168.1.1"

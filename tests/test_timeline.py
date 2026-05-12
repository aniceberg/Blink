from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.timeline import TimelinePlanner, choose_strategy


def test_timeline_respects_daily_window():
    tz = ZoneInfo("America/New_York")
    planner = TimelinePlanner("America/New_York")
    timestamps = planner.expand(
        start_at=datetime(2026, 1, 1, 0, 0, tzinfo=tz),
        end_at=datetime(2026, 1, 1, 23, 0, tzinfo=tz),
        daily_start="07:00",
        daily_end="07:03",
        interval_seconds=60,
    )
    assert [ts.strftime("%H:%M") for ts in timestamps] == ["07:00", "07:01", "07:02", "07:03"]


def test_strategy_selection():
    assert choose_strategy(1) == "export"
    assert choose_strategy(10) == "export"
    assert choose_strategy(30) == "snapshot"
    assert choose_strategy(60) == "snapshot"


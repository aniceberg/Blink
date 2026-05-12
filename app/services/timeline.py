from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


def parse_hhmm(value: str) -> time:
    parts = [int(part) for part in value.split(":")]
    if len(parts) == 2:
        parts.append(0)
    hour, minute, second = parts
    return time(hour, minute, second)


class TimelinePlanner:
    def __init__(self, timezone_name: str):
        self.timezone = ZoneInfo(timezone_name)

    def expand(
        self,
        *,
        start_at: datetime,
        end_at: datetime,
        daily_start: str,
        daily_end: str,
        interval_seconds: int,
    ) -> list[datetime]:
        if end_at <= start_at:
            raise ValueError("End time must be after start time.")

        start_at = start_at.astimezone(self.timezone)
        end_at = end_at.astimezone(self.timezone)
        window_start = parse_hhmm(daily_start)
        window_end = parse_hhmm(daily_end)

        timestamps: list[datetime] = []
        day = start_at.date()
        last_day = end_at.date()
        step = timedelta(seconds=interval_seconds)

        while day <= last_day:
            day_start = datetime.combine(day, window_start, self.timezone)
            day_end = datetime.combine(day, window_end, self.timezone)
            if window_end <= window_start:
                day_end += timedelta(days=1)

            current = max(day_start, start_at)
            limit = min(day_end, end_at)
            while current <= limit:
                timestamps.append(current)
                current += step

            day += timedelta(days=1)

        return timestamps


def choose_strategy(sample_interval_seconds: int) -> str:
    return "snapshot" if sample_interval_seconds >= 30 else "export"

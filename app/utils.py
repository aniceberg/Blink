from __future__ import annotations

import re
import subprocess
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo


SIMPLE_INTERVAL_RE = re.compile(r"^\s*(\d+)\s*([smh]|sec|secs|second|seconds|min|mins|minute|minutes|hour|hours)\s*$", re.I)
FRAMES_PER_RE = re.compile(r"^\s*(\d+)\s*(?:frame|frames)\s*(?:per|/)\s*(?:(\d+)\s*)?([smh]|sec|secs|second|seconds|min|mins|minute|minutes|hour|hours)\s*$", re.I)
GATEWAY_RE = re.compile(r"^\s*gateway:\s*([0-9a-fA-F:.]+)\s*$", re.M)


def parse_interval(value: str | int) -> int:
    if isinstance(value, int):
        seconds = value
    else:
        raw = value.strip().lower()
        if raw.isdigit():
            seconds = int(raw)
        else:
            simple = SIMPLE_INTERVAL_RE.match(raw)
            frames_per = FRAMES_PER_RE.match(raw)
            if simple:
                amount, unit = simple.groups()
                amount = int(amount)
                frames = 1
            elif frames_per:
                frames_part, amount_part, unit = frames_per.groups()
                frames = int(frames_part)
                amount = int(amount_part or "1")
            else:
                raise ValueError("Use intervals like 1s, 10s, 1m, 5 minutes, or 1 hour.")
            if frames != 1:
                if amount == 1 and unit.startswith("min"):
                    return max(1, 60 // frames)
                raise ValueError("Blink supports one sampled frame every N seconds/minutes/hours.")
            if unit in {"s", "sec", "secs", "second", "seconds"}:
                seconds = amount
            elif unit in {"m", "min", "mins", "minute", "minutes"}:
                seconds = amount * 60
            elif unit in {"h", "hour", "hours"}:
                seconds = amount * 3600
            else:
                raise ValueError("Unsupported interval unit.")
    if seconds < 1 or seconds > 86400:
        raise ValueError("Interval must be between 1 second and 24 hours.")
    return seconds


def parse_local_datetime(value: str | None, timezone: str) -> datetime | None:
    if not value:
        return None
    normalized = value.strip()
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(timezone))
    return dt


def parse_history_boundary(value: str | None, timezone: str, boundary_time: str) -> datetime | None:
    if not value:
        return None
    normalized = value.strip()
    if "T" in normalized:
        return parse_local_datetime(normalized, timezone)
    parsed_date = date.fromisoformat(normalized)
    parts = [int(part) for part in boundary_time.split(":")]
    if len(parts) == 2:
        parts.append(0)
    hour, minute, second = parts
    return datetime.combine(parsed_date, time(hour, minute, second), tzinfo=ZoneInfo(timezone))


def parse_clock_time(value: str) -> time:
    parts = [int(part) for part in value.split(":")]
    if len(parts) == 2:
        parts.append(0)
    hour, minute, second = parts
    return time(hour, minute, second)


def parse_submitted_date(value: str | None) -> date | None:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if "T" in normalized:
        return datetime.fromisoformat(normalized).date()
    return date.fromisoformat(normalized)


def parse_default_gateway(output: str) -> str | None:
    match = GATEWAY_RE.search(output)
    return match.group(1) if match else None


def detect_default_gateway() -> str | None:
    try:
        result = subprocess.run(
            ["route", "-n", "get", "default"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return None
    return parse_default_gateway(f"{result.stdout}\n{result.stderr}")


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return cleaned or "camera"


def inside_directory(path: Path, directory: Path) -> bool:
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False

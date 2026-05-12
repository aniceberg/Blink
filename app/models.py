from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class FrameStatus(StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    MISSING = "missing"
    FAILED = "failed"


@dataclass(frozen=True)
class Settings:
    id: int
    host: str
    api_key: str
    username: str | None
    password: str | None
    verify_ssl: bool
    timezone: str
    output_dir: str


@dataclass(frozen=True)
class Console:
    id: int
    name: str
    host: str
    api_key: str
    username: str | None
    password: str | None
    verify_ssl: bool
    enabled: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class Camera:
    camera_id: str
    console_id: int
    console_name: str
    protect_camera_id: str
    name: str
    model: str | None
    state: str | None
    is_connected: bool
    is_recording: bool
    raw: dict[str, Any]


@dataclass(frozen=True)
class Job:
    id: int
    status: JobStatus
    camera_ids: list[str]
    camera_names: list[str]
    start_at: datetime | None
    end_at: datetime | None
    earliest_available: bool
    daily_window_enabled: bool
    daily_start: str
    daily_end: str
    sample_interval_seconds: int
    output_fps: int
    encoder: str
    videotoolbox_quality: int
    x265_crf: int
    x265_preset: str
    output_scale_mode: str
    output_scale_width: int | None
    progress: float
    planned_frame_count: int
    processed_frame_count: int
    message: str
    output_path: str | None
    thumbnail_path: str | None
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    resolved_start_at: datetime | None
    resolved_end_at: datetime | None
    created_at: datetime
    updated_at: datetime

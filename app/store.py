from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

from app.config import DB_PATH, ensure_data_dirs
from app.models import Camera, Console, Job, JobStatus, Settings


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def console_name_from_host(host: str) -> str:
    parsed = urlparse(host if "://" in host else f"https://{host}")
    return parsed.hostname or host or "UniFi Console"


def camera_uid(console_id: int, protect_camera_id: str) -> str:
    return f"c{console_id}:{protect_camera_id}"


class Store:
    def __init__(self, db_path: Path = DB_PATH):
        ensure_data_dirs()
        self.db_path = db_path
        self.init_db()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    host TEXT NOT NULL DEFAULT '',
                    api_key TEXT NOT NULL DEFAULT '',
                    username TEXT,
                    password TEXT,
                    verify_ssl INTEGER NOT NULL DEFAULT 0,
                    timezone TEXT NOT NULL DEFAULT 'America/New_York',
                    output_dir TEXT NOT NULL DEFAULT 'data/media',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS cameras (
                    camera_id TEXT PRIMARY KEY,
                    console_id INTEGER,
                    protect_camera_id TEXT,
                    name TEXT NOT NULL,
                    model TEXT,
                    state TEXT,
                    is_connected INTEGER NOT NULL DEFAULT 0,
                    is_recording INTEGER NOT NULL DEFAULT 0,
                    raw_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS consoles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    host TEXT NOT NULL,
                    api_key TEXT NOT NULL DEFAULT '',
                    username TEXT,
                    password TEXT,
                    verify_ssl INTEGER NOT NULL DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    status TEXT NOT NULL,
                    camera_ids_json TEXT NOT NULL,
                    camera_names_json TEXT NOT NULL,
                    start_at TEXT,
                    end_at TEXT,
                    earliest_available INTEGER NOT NULL DEFAULT 0,
                    daily_window_enabled INTEGER NOT NULL DEFAULT 1,
                    daily_start TEXT NOT NULL,
                    daily_end TEXT NOT NULL,
                    sample_interval_seconds INTEGER NOT NULL,
                    output_fps INTEGER NOT NULL,
                    encoder TEXT NOT NULL DEFAULT 'hevc_videotoolbox',
                    videotoolbox_quality INTEGER NOT NULL DEFAULT 65,
                    x265_crf INTEGER NOT NULL,
                    x265_preset TEXT NOT NULL,
                    output_scale_mode TEXT NOT NULL DEFAULT 'original',
                    output_scale_width INTEGER,
                    progress REAL NOT NULL DEFAULT 0,
                    planned_frame_count INTEGER NOT NULL DEFAULT 0,
                    processed_frame_count INTEGER NOT NULL DEFAULT 0,
                    message TEXT NOT NULL DEFAULT '',
                    output_path TEXT,
                    thumbnail_path TEXT,
                    error TEXT,
                    started_at TEXT,
                    finished_at TEXT,
                    resolved_start_at TEXT,
                    resolved_end_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS frame_manifest (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    camera_id TEXT NOT NULL,
                    requested_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    source_method TEXT,
                    frame_path TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS artifacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    path TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                """
            )
            self._ensure_column(conn, "cameras", "console_id", "INTEGER")
            self._ensure_column(conn, "cameras", "protect_camera_id", "TEXT")
            self._ensure_column(conn, "jobs", "encoder", "TEXT NOT NULL DEFAULT 'hevc_videotoolbox'")
            self._ensure_column(conn, "jobs", "videotoolbox_quality", "INTEGER NOT NULL DEFAULT 65")
            self._ensure_column(conn, "jobs", "output_scale_mode", "TEXT NOT NULL DEFAULT 'original'")
            self._ensure_column(conn, "jobs", "output_scale_width", "INTEGER")
            self._ensure_column(conn, "jobs", "daily_window_enabled", "INTEGER NOT NULL DEFAULT 1")
            self._ensure_column(conn, "jobs", "planned_frame_count", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "jobs", "processed_frame_count", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "jobs", "started_at", "TEXT")
            self._ensure_column(conn, "jobs", "finished_at", "TEXT")
            self._ensure_column(conn, "jobs", "resolved_start_at", "TEXT")
            self._ensure_column(conn, "jobs", "resolved_end_at", "TEXT")
            row = conn.execute("SELECT id FROM settings WHERE id = 1").fetchone()
            if row is None:
                conn.execute("INSERT INTO settings (id, updated_at) VALUES (1, ?)", (utc_now(),))
            self._migrate_single_console(conn)
            self._migrate_camera_ids(conn)

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _migrate_single_console(self, conn: sqlite3.Connection) -> None:
        existing = conn.execute("SELECT id FROM consoles ORDER BY id LIMIT 1").fetchone()
        settings = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
        if existing is not None or settings is None or not settings["host"]:
            return
        now = utc_now()
        conn.execute(
            """
            INSERT INTO consoles (name, host, api_key, username, password, verify_ssl, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                console_name_from_host(settings["host"]),
                settings["host"].rstrip("/"),
                settings["api_key"] or "",
                settings["username"],
                settings["password"],
                1 if settings["verify_ssl"] else 0,
                now,
                now,
            ),
        )

    def _migrate_camera_ids(self, conn: sqlite3.Connection) -> None:
        first_console = conn.execute("SELECT id FROM consoles ORDER BY id LIMIT 1").fetchone()
        if first_console is None:
            return
        default_console_id = int(first_console["id"])
        rows = conn.execute("SELECT camera_id, console_id, protect_camera_id FROM cameras").fetchall()
        id_map: dict[str, str] = {}
        for row in rows:
            old_id = row["camera_id"]
            console_id = int(row["console_id"] or default_console_id)
            protect_id = row["protect_camera_id"] or old_id
            new_id = camera_uid(console_id, protect_id)
            if row["console_id"] is None or row["protect_camera_id"] is None:
                conn.execute(
                    "UPDATE cameras SET console_id = ?, protect_camera_id = ? WHERE camera_id = ?",
                    (console_id, protect_id, old_id),
                )
            if old_id == new_id:
                continue
            existing = conn.execute("SELECT camera_id FROM cameras WHERE camera_id = ?", (new_id,)).fetchone()
            if existing is None:
                conn.execute("UPDATE cameras SET camera_id = ? WHERE camera_id = ?", (new_id, old_id))
                id_map[old_id] = new_id
        if id_map:
            self._rewrite_job_camera_ids(conn, id_map)
            for old_id, new_id in id_map.items():
                conn.execute("UPDATE frame_manifest SET camera_id = ? WHERE camera_id = ?", (new_id, old_id))

    def _rewrite_job_camera_ids(self, conn: sqlite3.Connection, id_map: dict[str, str]) -> None:
        rows = conn.execute("SELECT id, camera_ids_json FROM jobs").fetchall()
        for row in rows:
            try:
                camera_ids = json.loads(row["camera_ids_json"])
            except json.JSONDecodeError:
                continue
            rewritten = [id_map.get(camera_id, camera_id) for camera_id in camera_ids]
            if rewritten != camera_ids:
                conn.execute("UPDATE jobs SET camera_ids_json = ? WHERE id = ?", (json.dumps(rewritten), row["id"]))

    def get_settings(self) -> Settings:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
        return Settings(
            id=row["id"],
            host=row["host"],
            api_key=row["api_key"],
            username=row["username"],
            password=row["password"],
            verify_ssl=bool(row["verify_ssl"]),
            timezone=row["timezone"],
            output_dir=row["output_dir"],
        )

    def save_settings(self, data: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE settings
                SET timezone = ?, output_dir = ?, updated_at = ?
                WHERE id = 1
                """,
                (
                    data.get("timezone") or "America/New_York",
                    data.get("output_dir") or "data/media",
                    utc_now(),
                ),
            )

    def list_consoles(self, enabled_only: bool = False) -> list[Console]:
        sql = "SELECT * FROM consoles"
        params: tuple[Any, ...] = ()
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY name, id"
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_console(row) for row in rows]

    def get_console(self, console_id: int) -> Console | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM consoles WHERE id = ?", (console_id,)).fetchone()
        return self._row_to_console(row) if row else None

    def create_console(self, data: dict[str, Any]) -> int:
        now = utc_now()
        host = data.get("host", "").rstrip("/")
        name = (data.get("name") or console_name_from_host(host)).strip()
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO consoles (name, host, api_key, username, password, verify_ssl, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    host,
                    data.get("api_key", ""),
                    data.get("username") or None,
                    data.get("password") or None,
                    1 if data.get("verify_ssl") else 0,
                    1 if data.get("enabled", True) else 0,
                    now,
                    now,
                ),
            )
            return int(cur.lastrowid)

    def update_console(self, console_id: int, data: dict[str, Any]) -> None:
        host = data.get("host", "").rstrip("/")
        name = (data.get("name") or console_name_from_host(host)).strip()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE consoles
                SET name = ?, host = ?, api_key = ?, username = ?, password = ?, verify_ssl = ?, enabled = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    name,
                    host,
                    data.get("api_key", ""),
                    data.get("username") or None,
                    data.get("password") or None,
                    1 if data.get("verify_ssl") else 0,
                    1 if data.get("enabled") else 0,
                    utc_now(),
                    console_id,
                ),
            )

    def delete_console(self, console_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM cameras WHERE console_id = ?", (console_id,))
            conn.execute("DELETE FROM consoles WHERE id = ?", (console_id,))

    def upsert_cameras(self, console: Console, cameras: list[Camera]) -> None:
        now = utc_now()
        with self.connect() as conn:
            for camera in cameras:
                uid = camera_uid(console.id, camera.protect_camera_id or camera.camera_id)
                conn.execute(
                    """
                    INSERT INTO cameras (
                        camera_id, console_id, protect_camera_id, name, model, state, is_connected, is_recording, raw_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(camera_id) DO UPDATE SET
                        console_id = excluded.console_id,
                        protect_camera_id = excluded.protect_camera_id,
                        name = excluded.name,
                        model = excluded.model,
                        state = excluded.state,
                        is_connected = excluded.is_connected,
                        is_recording = excluded.is_recording,
                        raw_json = excluded.raw_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        uid,
                        console.id,
                        camera.protect_camera_id or camera.camera_id,
                        camera.name,
                        camera.model,
                        camera.state,
                        1 if camera.is_connected else 0,
                        1 if camera.is_recording else 0,
                        json.dumps(camera.raw),
                        now,
                    ),
                )

    def list_cameras(self, enabled_consoles_only: bool = False) -> list[Camera]:
        where = "WHERE consoles.enabled = 1" if enabled_consoles_only else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT cameras.*, consoles.name AS console_name
                FROM cameras
                LEFT JOIN consoles ON consoles.id = cameras.console_id
                {where}
                ORDER BY cameras.name
                """
            ).fetchall()
        return [self._row_to_camera(row) for row in rows]

    def get_cameras_by_ids(self, camera_ids: list[str]) -> list[Camera]:
        if not camera_ids:
            return []
        placeholders = ",".join("?" for _ in camera_ids)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT cameras.*, consoles.name AS console_name
                FROM cameras
                LEFT JOIN consoles ON consoles.id = cameras.console_id
                WHERE camera_id IN ({placeholders})
                """,
                camera_ids,
            ).fetchall()
        by_id = {row["camera_id"]: self._row_to_camera(row) for row in rows}
        return [by_id[camera_id] for camera_id in camera_ids if camera_id in by_id]

    def create_job(self, data: dict[str, Any], camera_names: list[str]) -> int:
        now = utc_now()
        with self.connect() as conn:
            cur = conn.execute(
                    """
                    INSERT INTO jobs (
                    status, camera_ids_json, camera_names_json, start_at, end_at, earliest_available,
                    daily_window_enabled, daily_start, daily_end, sample_interval_seconds, output_fps, encoder,
                    videotoolbox_quality, x265_crf, x265_preset, output_scale_mode, output_scale_width,
                    progress, message, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (
                    JobStatus.QUEUED.value,
                    json.dumps(data["camera_ids"]),
                    json.dumps(camera_names),
                    data["start_at"].isoformat() if data.get("start_at") else None,
                    data["end_at"].isoformat() if data.get("end_at") else None,
                    1 if data.get("earliest_available") else 0,
                    1 if data.get("daily_window_enabled") else 0,
                    data["daily_start"],
                    data["daily_end"],
                    data["sample_interval_seconds"],
                    data["output_fps"],
                    data["encoder"],
                    data["videotoolbox_quality"],
                    data["x265_crf"],
                    data["x265_preset"],
                    data.get("output_scale_mode", "original"),
                    data.get("output_scale_width"),
                    "Queued",
                    now,
                    now,
                ),
            )
            return int(cur.lastrowid)

    def list_jobs(self, limit: int = 100) -> list[Job]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [self._row_to_job(row) for row in rows]

    def get_job(self, job_id: int) -> Job | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._row_to_job(row) if row else None

    def next_queued_job(self) -> Job | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE status = ? ORDER BY id LIMIT 1", (JobStatus.QUEUED.value,)).fetchone()
        return self._row_to_job(row) if row else None

    def update_job(self, job_id: int, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = utc_now()
        names = ", ".join(f"{key} = ?" for key in fields)
        values = [value.value if isinstance(value, JobStatus) else value for value in fields.values()]
        values.append(job_id)
        with self.connect() as conn:
            conn.execute(f"UPDATE jobs SET {names} WHERE id = ?", values)

    def reset_job(self, job_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM frame_manifest WHERE job_id = ?", (job_id,))
            conn.execute("DELETE FROM artifacts WHERE job_id = ?", (job_id,))
            conn.execute(
                """
                UPDATE jobs SET status = ?, progress = 0, message = ?, output_path = NULL,
                    thumbnail_path = NULL, error = NULL, planned_frame_count = 0,
                    processed_frame_count = 0, started_at = NULL, finished_at = NULL,
                    resolved_start_at = NULL, resolved_end_at = NULL, updated_at = ?
                WHERE id = ?
                """,
                (JobStatus.QUEUED.value, "Queued for retry", utc_now(), job_id),
            )

    def cancel_job(self, job_id: int) -> None:
        self.update_job(job_id, status=JobStatus.CANCELED, message="Canceled")

    def is_job_canceled(self, job_id: int) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return bool(row and row["status"] == JobStatus.CANCELED.value)

    def increment_processed_frame_count(self, job_id: int, amount: int = 1) -> tuple[int, int]:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET processed_frame_count = processed_frame_count + ?, updated_at = ?
                WHERE id = ?
                """,
                (amount, utc_now(), job_id),
            )
            row = conn.execute(
                "SELECT processed_frame_count, planned_frame_count FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        return int(row["processed_frame_count"]), int(row["planned_frame_count"])

    def add_frame(self, job_id: int, camera_id: str, requested_at: datetime, status: str, source_method: str | None = None, frame_path: str | None = None, error: str | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO frame_manifest (
                    job_id, camera_id, requested_at, status, source_method, frame_path, error, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (job_id, camera_id, requested_at.isoformat(), status, source_method, frame_path, error, utc_now()),
            )

    def list_frames(self, job_id: int) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM frame_manifest WHERE job_id = ? ORDER BY requested_at", (job_id,)).fetchall()

    def add_artifact(self, job_id: int, kind: str, path: str, metadata: dict[str, Any] | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO artifacts (job_id, kind, path, metadata_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (job_id, kind, path, json.dumps(metadata or {}), utc_now()),
            )

    def list_artifacts(self, job_id: int) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM artifacts WHERE job_id = ?", (job_id,)).fetchall()

    def delete_job(self, job_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM frame_manifest WHERE job_id = ?", (job_id,))
            conn.execute("DELETE FROM artifacts WHERE job_id = ?", (job_id,))
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

    def _row_to_console(self, row: sqlite3.Row) -> Console:
        return Console(
            id=row["id"],
            name=row["name"],
            host=row["host"],
            api_key=row["api_key"],
            username=row["username"],
            password=row["password"],
            verify_ssl=bool(row["verify_ssl"]),
            enabled=bool(row["enabled"]),
            created_at=parse_dt(row["created_at"]),
            updated_at=parse_dt(row["updated_at"]),
        )

    def _row_to_camera(self, row: sqlite3.Row) -> Camera:
        console_id = int(row["console_id"] or 0)
        protect_camera_id = row["protect_camera_id"] or row["camera_id"]
        return Camera(
            camera_id=row["camera_id"],
            console_id=console_id,
            console_name=row["console_name"] or f"Console {console_id}",
            protect_camera_id=protect_camera_id,
            name=row["name"],
            model=row["model"],
            state=row["state"],
            is_connected=bool(row["is_connected"]),
            is_recording=bool(row["is_recording"]),
            raw=json.loads(row["raw_json"] or "{}"),
        )

    def _row_to_job(self, row: sqlite3.Row) -> Job:
        return Job(
            id=row["id"],
            status=JobStatus(row["status"]),
            camera_ids=json.loads(row["camera_ids_json"]),
            camera_names=json.loads(row["camera_names_json"]),
            start_at=parse_dt(row["start_at"]),
            end_at=parse_dt(row["end_at"]),
            earliest_available=bool(row["earliest_available"]),
            daily_window_enabled=bool(row["daily_window_enabled"]),
            daily_start=row["daily_start"],
            daily_end=row["daily_end"],
            sample_interval_seconds=row["sample_interval_seconds"],
            output_fps=row["output_fps"],
            encoder=row["encoder"],
            videotoolbox_quality=row["videotoolbox_quality"],
            x265_crf=row["x265_crf"],
            x265_preset=row["x265_preset"],
            output_scale_mode=row["output_scale_mode"],
            output_scale_width=row["output_scale_width"],
            progress=row["progress"],
            planned_frame_count=row["planned_frame_count"],
            processed_frame_count=row["processed_frame_count"],
            message=row["message"],
            output_path=row["output_path"],
            thumbnail_path=row["thumbnail_path"],
            error=row["error"],
            started_at=parse_dt(row["started_at"]),
            finished_at=parse_dt(row["finished_at"]),
            resolved_start_at=parse_dt(row["resolved_start_at"]),
            resolved_end_at=parse_dt(row["resolved_end_at"]),
            created_at=parse_dt(row["created_at"]),
            updated_at=parse_dt(row["updated_at"]),
        )

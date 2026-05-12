from __future__ import annotations

import shutil
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import available_timezones

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import (
    DEFAULT_DAILY_END,
    DEFAULT_DAILY_START,
    DEFAULT_ENCODER,
    DEFAULT_OUTPUT_FPS,
    DEFAULT_SAMPLE_INTERVAL_SECONDS,
    DEFAULT_VIDEOTOOLBOX_QUALITY,
    DEFAULT_X265_CRF,
    DEFAULT_X265_PRESET,
    EXPORTS_DIR,
    FRAMES_DIR,
    MEDIA_DIR,
    PROJECT_ROOT,
    ensure_data_dirs,
    resource_path,
)
from app.compat import ensure_importlib_resources
from app.models import JobStatus
from app.paths import resolve_output_dir
from app.services.ffmpeg import check_ffmpeg
from app.services.jobs import JobRunner, describe_output_scale
from app.services.snapshots import SnapshotCache
from app.services.unifi import UniFiClient
from app.store import Store
from app.utils import (
    detect_default_gateway,
    inside_directory,
    parse_clock_time,
    parse_history_boundary,
    parse_interval,
    parse_submitted_date,
)

ensure_data_dirs()
ensure_importlib_resources()
store = Store()
runner = JobRunner(store)
snapshot_cache = SnapshotCache()
templates = Jinja2Templates(directory=str(resource_path("app/templates")))
templates.env.cache = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    runner.start()
    yield
    await runner.stop()


app = FastAPI(title="Blink", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(resource_path("app/static"))), name="static")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


def context(request: Request, **kwargs):
    settings = store.get_settings()
    return {
        "request": request,
        "settings": settings,
        "consoles": store.list_consoles(),
        "project_root": PROJECT_ROOT,
        "ffmpeg": check_ffmpeg(),
        "defaults": {
            "daily_start": DEFAULT_DAILY_START,
            "daily_end": DEFAULT_DAILY_END,
            "sample_interval": DEFAULT_SAMPLE_INTERVAL_SECONDS,
            "output_fps": DEFAULT_OUTPUT_FPS,
            "encoder": DEFAULT_ENCODER,
            "videotoolbox_quality": DEFAULT_VIDEOTOOLBOX_QUALITY,
            "x265_crf": DEFAULT_X265_CRF,
            "x265_preset": DEFAULT_X265_PRESET,
            "output_scale_mode": "original",
            "output_scale_width": None,
        },
        "describe_output_scale": describe_output_scale,
        **kwargs,
    }


def render(request: Request, template_name: str, **kwargs):
    return templates.TemplateResponse(request, template_name, context(request, **kwargs))


def iso_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def elapsed_seconds(job) -> int | None:
    if job.status == JobStatus.QUEUED or not job.started_at:
        return None
    end = job.finished_at or datetime.now(timezone.utc)
    started = job.started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return max(0, int((end - started).total_seconds()))


def job_status_payload(job) -> dict:
    progress = 0 if job.status == JobStatus.QUEUED else job.progress
    return {
        "id": job.id,
        "status": job.status.value,
        "progress": progress,
        "message": job.message,
        "error": job.error,
        "started_at": iso_or_none(job.started_at),
        "finished_at": iso_or_none(job.finished_at),
        "elapsed_seconds": elapsed_seconds(job),
        "resolved_start_at": iso_or_none(job.resolved_start_at),
        "resolved_end_at": iso_or_none(job.resolved_end_at),
        "daily_window_enabled": job.daily_window_enabled,
        "daily_start": job.daily_start,
        "daily_end": job.daily_end,
        "output_scale": describe_output_scale(job.output_scale_mode, job.output_scale_width),
        "planned_frame_count": job.planned_frame_count,
        "processed_frame_count": job.processed_frame_count,
    }


def parse_output_scale(mode: str, custom_width: str) -> tuple[str, int | None]:
    presets = {
        "original": None,
        "max_3840": 3840,
        "max_1920": 1920,
        "max_1280": 1280,
    }
    if mode in presets:
        return mode, presets[mode]
    if mode != "custom":
        raise ValueError("Choose a supported output resolution.")
    try:
        width = int((custom_width or "").strip())
    except ValueError as exc:
        raise ValueError("Custom output width must be a number.") from exc
    if width < 64 or width > 8192:
        raise ValueError("Custom output width must be between 64 and 8192 pixels.")
    return "custom", width


def validate_daily_window_range(
    *,
    daily_window_enabled: bool,
    daily_start: str,
    daily_end: str,
    earliest_available: bool,
    start_at: str,
    end_at: str,
) -> None:
    if not daily_window_enabled:
        return
    if parse_clock_time(daily_end) > parse_clock_time(daily_start):
        return
    if earliest_available:
        return
    start_date = parse_submitted_date(start_at)
    end_date = parse_submitted_date(end_at)
    if start_date and end_date and end_date <= start_date:
        raise ValueError("Overnight daily windows require an end date after the start date.")


def cleanup_job_files(job_id: int) -> None:
    job = store.get_job(job_id)
    if not job:
        return
    settings_output_dir = resolve_output_dir(store.get_settings().output_dir)
    allowed_roots = [settings_output_dir, MEDIA_DIR, FRAMES_DIR, EXPORTS_DIR, PROJECT_ROOT / "data"]
    candidates = [FRAMES_DIR / f"job_{job_id}", EXPORTS_DIR / f"job_{job_id}"]
    for raw_path in (job.output_path, job.thumbnail_path):
        if raw_path:
            path = Path(raw_path)
            candidates.append(path)
            if path.parent.name == f"job_{job_id}":
                candidates.append(path.parent)
                allowed_roots.append(path.parent)
    for artifact in store.list_artifacts(job_id):
        path = Path(artifact["path"])
        candidates.append(path)
        if path.parent.name == f"job_{job_id}":
            candidates.append(path.parent)
            allowed_roots.append(path.parent)

    for path in sorted({candidate.resolve() for candidate in candidates}, key=lambda item: len(item.parts), reverse=True):
        if not any(inside_directory(path, root) for root in allowed_roots):
            continue
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink(missing_ok=True)


def safe_job_output_path(job_id: int) -> Path:
    job = store.get_job(job_id)
    if not job or not job.output_path:
        raise HTTPException(status_code=404)
    path = Path(job.output_path)
    allowed_roots = [resolve_output_dir(store.get_settings().output_dir), MEDIA_DIR, PROJECT_ROOT / "data"]
    if not any(inside_directory(path, root) for root in allowed_roots) or not path.exists():
        raise HTTPException(status_code=404)
    return path


def safe_job_thumbnail_path(job_id: int) -> Path:
    job = store.get_job(job_id)
    if not job or not job.thumbnail_path:
        raise HTTPException(status_code=404)
    path = Path(job.thumbnail_path)
    allowed_roots = [resolve_output_dir(store.get_settings().output_dir), MEDIA_DIR, PROJECT_ROOT / "data"]
    if not any(inside_directory(path, root) for root in allowed_roots) or not path.exists():
        raise HTTPException(status_code=404)
    return path


@app.get("/")
async def home(request: Request):
    cameras = store.list_cameras()
    jobs = store.list_jobs(limit=8)
    return render(request, "dashboard.html", cameras=cameras, jobs=jobs)


_timezones = sorted(available_timezones())


@app.get("/setup")
async def setup_get(request: Request):
    return render(request, "setup.html", saved=False, error=None, timezones=_timezones)


@app.post("/setup")
async def setup_post(
    request: Request,
    timezone: str = Form("America/New_York"),
    output_dir: str = Form("data/media"),
):
    sanitized_output_dir = (output_dir or "data/media").strip() or "data/media"
    try:
        resolved_output_dir = resolve_output_dir(sanitized_output_dir)
        resolved_output_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return render(request, "setup.html", saved=False, error=f"Could not create output directory: {exc}")

    store.save_settings(
        {
            "timezone": timezone,
            "output_dir": sanitized_output_dir,
        }
    )
    return render(request, "setup.html", saved=True, error=None, timezones=_timezones)


@app.post("/setup/consoles")
async def setup_console_create(
    name: str = Form(""),
    host: str = Form(...),
    api_key: str = Form(""),
    username: str = Form(""),
    password: str = Form(""),
    verify_ssl: str | None = Form(None),
    enabled: str | None = Form("on"),
):
    store.create_console(
        {
            "name": name,
            "host": host,
            "api_key": api_key,
            "username": username,
            "password": password,
            "verify_ssl": bool(verify_ssl),
            "enabled": bool(enabled),
        }
    )
    return RedirectResponse("/setup", status_code=303)


@app.post("/setup/consoles/{console_id}")
async def setup_console_update(
    console_id: int,
    name: str = Form(""),
    host: str = Form(...),
    api_key: str = Form(""),
    username: str = Form(""),
    password: str = Form(""),
    verify_ssl: str | None = Form(None),
    enabled: str | None = Form(None),
):
    if not store.get_console(console_id):
        raise HTTPException(status_code=404)
    store.update_console(
        console_id,
        {
            "name": name,
            "host": host,
            "api_key": api_key,
            "username": username,
            "password": password,
            "verify_ssl": bool(verify_ssl),
            "enabled": bool(enabled),
        },
    )
    return RedirectResponse("/setup", status_code=303)


@app.post("/setup/consoles/{console_id}/delete")
async def setup_console_delete(console_id: int):
    if not store.get_console(console_id):
        raise HTTPException(status_code=404)
    store.delete_console(console_id)
    return RedirectResponse("/setup", status_code=303)


@app.get("/setup/detect-host")
async def setup_detect_host():
    gateway = detect_default_gateway()
    if not gateway:
        return JSONResponse({"error": "Could not detect a default gateway."}, status_code=404)
    return {"host": f"https://{gateway}", "gateway": gateway}


@app.get("/cameras")
async def cameras_get(request: Request):
    return render(request, "cameras.html", cameras=store.list_cameras(enabled_consoles_only=True), active_consoles=store.list_consoles(enabled_only=True), error=None)


@app.post("/cameras/refresh")
async def cameras_refresh(request: Request):
    consoles = store.list_consoles(enabled_only=True)
    if not consoles:
        return render(request, "cameras.html", cameras=store.list_cameras(enabled_consoles_only=True), active_consoles=consoles, error="Configure and enable at least one UniFi console first.")
    errors: list[str] = []
    refreshed = 0
    for console in consoles:
        if not console.host:
            errors.append(f"{console.name}: missing host")
            continue
        try:
            cameras = await UniFiClient(console).list_cameras()
            store.upsert_cameras(console, cameras)
            refreshed += 1
        except Exception as exc:
            errors.append(f"{console.name}: {exc}")
    if errors:
        message = "; ".join(errors)
        if refreshed:
            message = f"Refreshed {refreshed} console(s), but some failed: {message}"
        return render(request, "cameras.html", cameras=store.list_cameras(enabled_consoles_only=True), active_consoles=consoles, error=message)
    return RedirectResponse("/cameras", status_code=303)


@app.get("/cameras/{camera_id}/snapshot")
async def camera_snapshot(camera_id: str, refresh: bool = Query(False)):
    cameras = store.get_cameras_by_ids([camera_id])
    if not cameras:
        raise HTTPException(status_code=404, detail="Camera not found.")
    camera = cameras[0]
    console = store.get_console(camera.console_id)
    if not console or not console.enabled:
        raise HTTPException(status_code=400, detail="Camera console is missing or disabled.")
    try:
        entry = await snapshot_cache.get_or_fetch(
            camera_id=camera_id,
            protect_camera_id=camera.protect_camera_id,
            client=UniFiClient(console),
            refresh=refresh,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(
        content=entry.content,
        media_type=entry.content_type,
        headers={"Cache-Control": "private, max-age=60"},
    )


@app.get("/jobs")
async def jobs_get(request: Request):
    return render(request, "jobs.html", jobs=store.list_jobs())


@app.get("/jobs/new")
async def job_new_get(request: Request):
    return render(request, "job_new.html", cameras=store.list_cameras(enabled_consoles_only=True), active_consoles=store.list_consoles(enabled_only=True), error=None)


@app.post("/jobs/new")
async def job_new_post(
    request: Request,
    camera_ids: list[str] = Form(...),
    earliest_available: str | None = Form(None),
    start_at: str = Form(""),
    end_at: str = Form(""),
    daily_window_enabled: str | None = Form(None),
    daily_start: str = Form(DEFAULT_DAILY_START),
    daily_end: str = Form(DEFAULT_DAILY_END),
    sample_interval: str = Form("1m"),
    output_fps: int = Form(DEFAULT_OUTPUT_FPS),
    encoder: str = Form(DEFAULT_ENCODER),
    videotoolbox_quality: int = Form(DEFAULT_VIDEOTOOLBOX_QUALITY),
    x265_crf: int = Form(DEFAULT_X265_CRF),
    x265_preset: str = Form(DEFAULT_X265_PRESET),
    output_scale_mode: str = Form("original"),
    output_scale_width: str = Form(""),
):
    settings = store.get_settings()
    try:
        use_daily_window = bool(daily_window_enabled)
        validate_daily_window_range(
            daily_window_enabled=use_daily_window,
            daily_start=daily_start,
            daily_end=daily_end,
            earliest_available=bool(earliest_available),
            start_at=start_at,
            end_at=end_at,
        )
        effective_daily_start = daily_start if use_daily_window else "00:00:00"
        effective_daily_end = daily_end if use_daily_window else "23:59:59"
        interval_seconds = parse_interval(sample_interval)
        if output_fps < 1 or output_fps > 120:
            raise ValueError("Output FPS must be between 1 and 120.")
        if encoder not in {"hevc_videotoolbox", "libx265"}:
            raise ValueError("Choose a supported HEVC encoder.")
        if videotoolbox_quality < 0 or videotoolbox_quality > 100:
            raise ValueError("VideoToolbox quality must be between 0 and 100.")
        if x265_crf < 0 or x265_crf > 51:
            raise ValueError("x265 CRF must be between 0 and 51.")
        scale_mode, scale_width = parse_output_scale(output_scale_mode, output_scale_width)
        cameras = store.get_cameras_by_ids(camera_ids)
        if not cameras:
            raise ValueError("Select at least one known camera.")
        consoles_by_id = {camera.console_id: store.get_console(camera.console_id) for camera in cameras}
        disabled = [
            camera.console_name
            for camera in cameras
            if not (consoles_by_id.get(camera.console_id) and consoles_by_id[camera.console_id].enabled)
        ]
        if disabled:
            raise ValueError(f"Selected cameras belong to disabled consoles: {', '.join(sorted(set(disabled)))}.")
        data = {
            "camera_ids": camera_ids,
            "start_at": parse_history_boundary(start_at, settings.timezone, effective_daily_start),
            "end_at": parse_history_boundary(end_at, settings.timezone, effective_daily_end),
            "earliest_available": bool(earliest_available),
            "daily_window_enabled": use_daily_window,
            "daily_start": effective_daily_start,
            "daily_end": effective_daily_end,
            "sample_interval_seconds": interval_seconds,
            "output_fps": output_fps,
            "encoder": encoder,
            "videotoolbox_quality": videotoolbox_quality,
            "x265_crf": x265_crf,
            "x265_preset": x265_preset,
            "output_scale_mode": scale_mode,
            "output_scale_width": scale_width,
        }
        if data["start_at"] and data["end_at"] and data["end_at"] < data["start_at"]:
            raise ValueError("End date must be on or after the start date.")
        if not data["earliest_available"] and not data["start_at"]:
            raise ValueError("Choose earliest available or provide a start date.")
        job_id = store.create_job(data, [camera.name for camera in cameras])
        return RedirectResponse(f"/jobs/{job_id}", status_code=303)
    except Exception as exc:
        return render(request, "job_new.html", cameras=store.list_cameras(enabled_consoles_only=True), active_consoles=store.list_consoles(enabled_only=True), error=str(exc))


@app.get("/jobs/{job_id}")
async def job_detail(request: Request, job_id: int):
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404)
    frames = store.list_frames(job_id)
    return render(request, "job_detail.html", job=job, frames=frames[-200:], elapsed_seconds=elapsed_seconds(job))


@app.get("/jobs/{job_id}/status")
async def job_status(job_id: int):
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404)
    return JSONResponse(job_status_payload(job), headers={"Cache-Control": "no-store"})


@app.post("/jobs/{job_id}/retry")
async def job_retry(job_id: int):
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404)
    store.reset_job(job_id)
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@app.post("/jobs/{job_id}/cancel")
async def job_cancel(job_id: int):
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404)
    if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
        store.cancel_job(job_id)
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@app.post("/jobs/{job_id}/delete")
async def job_delete(job_id: int):
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404)
    if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
        raise HTTPException(status_code=409, detail="Cancel the job before deleting it.")
    cleanup_job_files(job_id)
    store.delete_job(job_id)
    return RedirectResponse("/jobs", status_code=303)


@app.get("/media/{job_id}")
async def media(job_id: int):
    path = safe_job_output_path(job_id)
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@app.get("/jobs/{job_id}/reveal")
async def job_reveal(job_id: int):
    path = safe_job_output_path(job_id)
    return {"path": str(path), "name": path.name}


@app.get("/jobs/{job_id}/thumbnail")
async def job_thumbnail(job_id: int):
    path = safe_job_thumbnail_path(job_id)
    return FileResponse(path, media_type="image/jpeg", filename=path.name)

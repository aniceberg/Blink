from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from app.compat import ensure_importlib_resources
from app.models import Camera, Settings


class UniFiError(RuntimeError):
    pass


class UniFiClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.host = settings.host.rstrip("/")
        self._cookies: httpx.Cookies | None = None

    def _integration_url(self, path: str) -> str:
        return f"{self.host}/proxy/protect/integration/v1/{path.lstrip('/')}"

    def _protect_url(self, path: str) -> str:
        return f"{self.host}/proxy/protect/api/{path.lstrip('/')}"

    def _headers(self, accept: str = "application/json") -> dict[str, str]:
        headers = {"Accept": accept}
        if self.settings.api_key:
            headers["X-API-KEY"] = self.settings.api_key
        return headers

    def _private_headers(self, accept: str = "application/json") -> dict[str, str]:
        headers = {"Accept": accept}
        if self.settings.api_key:
            headers["X-API-KEY"] = self.settings.api_key
        return headers

    async def _client(self) -> httpx.AsyncClient:
        ensure_importlib_resources()
        return httpx.AsyncClient(verify=self.settings.verify_ssl, timeout=httpx.Timeout(60.0), follow_redirects=True)

    async def test_login(self) -> None:
        if not (self.settings.username and self.settings.password):
            raise UniFiError("Username and password are required.")
        async with await self._client() as client:
            await self.login_private_api(client)

    async def login_private_api(self, client: httpx.AsyncClient) -> None:
        if self._cookies or not (self.settings.username and self.settings.password):
            if self._cookies:
                client.cookies = self._cookies
            return
        login_url = f"{self.host}/api/auth/login"
        response = await client.post(
            login_url,
            json={"username": self.settings.username, "password": self.settings.password},
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        if response.status_code >= 400:
            raise UniFiError(f"Private API login failed with HTTP {response.status_code}.")
        self._cookies = client.cookies

    async def list_cameras(self) -> list[Camera]:
        async with await self._client() as client:
            response = await client.get(self._integration_url("/cameras"), headers=self._headers())
            if response.status_code >= 400:
                raise UniFiError(f"Camera discovery failed with HTTP {response.status_code}: {response.text[:300]}")
            data = response.json()
            cameras_data = data if isinstance(data, list) else data.get("data", [])
            return [self._camera_from_payload(item) for item in cameras_data]

    async def download_live_snapshot(self, camera_id: str) -> tuple[bytes, str]:
        async with await self._client() as client:
            response = await client.get(
                self._integration_url(f"/cameras/{camera_id}/snapshot"),
                headers=self._headers("image/jpeg"),
            )
            content_type = response.headers.get("content-type", "")
            if response.status_code >= 400:
                raise UniFiError(f"Live snapshot failed with HTTP {response.status_code}: {response.text[:200]}")
            if not content_type.startswith("image/"):
                raise UniFiError(f"Live snapshot returned non-image content: {content_type or 'unknown'}")
            if len(response.content) < 1000:
                raise UniFiError("Live snapshot response was too small to be valid.")
            return response.content, content_type

    async def download_recording_snapshot(self, camera_id: str, timestamp: datetime, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        ts_ms = int(timestamp.timestamp() * 1000)
        private_url = self._protect_url(f"/cameras/{camera_id}/recording-snapshot")
        integration_url = self._integration_url(f"/cameras/{camera_id}/snapshot")
        candidates = [
            (private_url, {"ts": ts_ms}, self._private_headers("image/jpeg")),
            (private_url, {"start": ts_ms - 500, "end": ts_ms + 500}, self._private_headers("image/jpeg")),
        ]
        async with await self._client() as client:
            await self.login_private_api(client)
            attempt_errors: list[str] = []
            for url, params, headers in candidates:
                response = await client.get(url, params=params, headers=headers)
                if response.status_code == 200 and response.headers.get("content-type", "").startswith("image/"):
                    output_path.write_bytes(response.content)
                    if output_path.stat().st_size < 1000:
                        raise UniFiError("Snapshot response was too small to be valid.")
                    return
                attempt_errors.append(f"{params}: HTTP {response.status_code}: {response.text[:200]}")
            raise UniFiError(f"Historical snapshot failed for {camera_id} at {timestamp.isoformat()}: {'; '.join(attempt_errors)}")

    async def export_video(self, camera_id: str, start_at: datetime, end_at: datetime, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        start_ms = int(start_at.timestamp() * 1000)
        end_ms = int(end_at.timestamp() * 1000)
        candidates = [
            (self._protect_url("/video/export"), {"camera": camera_id, "start": start_ms, "end": end_ms}, self._private_headers("video/mp4")),
            (self._protect_url("/video/export"), {"camera": camera_id, "startTime": start_ms, "endTime": end_ms}, self._private_headers("video/mp4")),
            (self._protect_url(f"/cameras/{camera_id}/video/export"), {"start": start_ms, "end": end_ms}, self._private_headers("video/mp4")),
        ]
        async with await self._client() as client:
            await self.login_private_api(client)
            attempt_errors: list[str] = []
            for url, params, headers in candidates:
                response = await client.get(url, params=params, headers=headers)
                if response.status_code == 200 and response.content:
                    output_path.write_bytes(response.content)
                    if output_path.stat().st_size < 1000:
                        raise UniFiError("Video export response was too small to be valid.")
                    return
                attempt_errors.append(f"{params}: HTTP {response.status_code}: {response.text[:200]}")
            raise UniFiError(f"Video export failed for {camera_id}: {'; '.join(attempt_errors)}")

    async def earliest_available(self, camera: Camera, fallback_end: datetime) -> datetime:
        found = self._find_oldest_timestamp(camera.raw)
        if found:
            return found
        # UniFi does not expose a stable oldest-recording endpoint in the official integration API.
        # Use a conservative probing default so "as far as possible" jobs can still be created.
        await asyncio.sleep(0)
        return fallback_end - timedelta(days=30)

    def _camera_from_payload(self, item: dict[str, Any]) -> Camera:
        feature_flags = item.get("featureFlags") or {}
        return Camera(
            camera_id=item.get("id", ""),
            console_id=0,
            console_name="",
            protect_camera_id=item.get("id", ""),
            name=item.get("name") or item.get("id", "Camera"),
            model=item.get("modelKey") or item.get("type"),
            state=item.get("state"),
            is_connected=item.get("state") == "CONNECTED" or bool(item.get("isConnected")),
            is_recording=bool(item.get("isRecording")),
            raw={**item, "featureFlags": feature_flags},
        )

    def _find_oldest_timestamp(self, payload: Any) -> datetime | None:
        if isinstance(payload, dict):
            for key, value in payload.items():
                lower = key.lower()
                if any(token in lower for token in ("oldest", "first", "recordingstart", "earliest")):
                    parsed = self._parse_timestamp(value)
                    if parsed:
                        return parsed
                nested = self._find_oldest_timestamp(value)
                if nested:
                    return nested
        elif isinstance(payload, list):
            for item in payload:
                nested = self._find_oldest_timestamp(item)
                if nested:
                    return nested
        return None

    def _parse_timestamp(self, value: Any) -> datetime | None:
        if isinstance(value, (int, float)):
            if value > 10_000_000_000:
                value = value / 1000
            if value > 0:
                return datetime.fromtimestamp(value).astimezone()
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None

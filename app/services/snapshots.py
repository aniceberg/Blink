from __future__ import annotations

import time
from dataclasses import dataclass

from app.services.unifi import UniFiClient


@dataclass(frozen=True)
class SnapshotEntry:
    camera_id: str
    content: bytes
    content_type: str
    fetched_at: float


class SnapshotCache:
    def __init__(self, ttl_seconds: int = 60, min_size: int = 1000):
        self.ttl_seconds = ttl_seconds
        self.min_size = min_size
        self._entries: dict[str, SnapshotEntry] = {}

    def get(self, camera_id: str) -> SnapshotEntry | None:
        entry = self._entries.get(camera_id)
        if entry is None:
            return None
        if time.time() - entry.fetched_at > self.ttl_seconds:
            self._entries.pop(camera_id, None)
            return None
        return entry

    def set(self, camera_id: str, content: bytes, content_type: str) -> SnapshotEntry:
        if len(content) < self.min_size:
            raise ValueError("Snapshot response was too small to be valid.")
        if not content_type.startswith("image/"):
            raise ValueError(f"Snapshot response was not an image: {content_type or 'unknown'}")
        entry = SnapshotEntry(camera_id=camera_id, content=content, content_type=content_type, fetched_at=time.time())
        self._entries[camera_id] = entry
        return entry

    async def get_or_fetch(self, *, camera_id: str, client: UniFiClient, protect_camera_id: str | None = None, refresh: bool = False) -> SnapshotEntry:
        if not refresh:
            cached = self.get(camera_id)
            if cached is not None:
                return cached
        content, content_type = await client.download_live_snapshot(protect_camera_id or camera_id)
        return self.set(camera_id, content, content_type)

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.services.snapshots import SnapshotCache


class FakeUniFiClient:
    def __init__(self):
        self.calls = 0

    async def download_live_snapshot(self, camera_id):
        self.calls += 1
        return b"x" * 1200, "image/jpeg"


@pytest.mark.asyncio
async def test_snapshot_cache_hit_and_refresh_bypass():
    cache = SnapshotCache(ttl_seconds=60, min_size=10)
    client = FakeUniFiClient()

    first = await cache.get_or_fetch(camera_id="camera-1", client=client)
    second = await cache.get_or_fetch(camera_id="camera-1", client=client)
    refreshed = await cache.get_or_fetch(camera_id="camera-1", client=client, refresh=True)

    assert first.content == second.content == refreshed.content
    assert client.calls == 2


def test_snapshot_cache_rejects_non_images():
    cache = SnapshotCache(min_size=1)
    with pytest.raises(ValueError):
        cache.set("camera-1", b"not-image", "text/plain")


def test_snapshot_route_rejects_unknown_camera():
    client = TestClient(main.app)
    response = client.get("/cameras/not-a-real-camera/snapshot")
    assert response.status_code == 404

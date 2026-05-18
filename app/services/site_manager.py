from __future__ import annotations

import httpx

BASE_URL = "https://api.ui.com"
_SITE_MANAGER_HEADERS = {"Accept": "application/json"}


def _auth_headers(api_key: str) -> dict[str, str]:
    return {**_SITE_MANAGER_HEADERS, "X-API-Key": api_key}


def _extract_rows(payload: object) -> list[object]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "hosts", "items"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return []


def _extract_applications(record: dict) -> list[str]:
    reported = record.get("reportedState") or {}
    controllers = reported.get("controllers")
    if not isinstance(controllers, list):
        return []
    names: list[str] = []
    for ctrl in controllers:
        if not isinstance(ctrl, dict):
            continue
        if ctrl.get("isInstalled") is False or ctrl.get("isRunning") is False:
            continue
        name = str(ctrl.get("name") or ctrl.get("application") or ctrl.get("type") or "").strip()
        if name:
            names.append(name.lower())
    return sorted(set(names))


def _normalize_host(row: object, index: int = 0) -> dict | None:
    if not isinstance(row, dict):
        return None
    reported = row.get("reportedState") or {}
    host_id = str(row.get("id") or row.get("hostId") or row.get("hostID") or "").strip()
    name = str(row.get("name") or reported.get("name") or "").strip()
    hostname = str(row.get("hostname") or reported.get("hostname") or "").strip()
    display_name = name or hostname or host_id or f"Host {index + 1}"
    return {
        "hostId": host_id,
        "displayName": display_name,
        "hostname": hostname or None,
        "applications": _extract_applications(row),
    }


async def list_hosts(api_key: str) -> list[dict]:
    """Return normalized host list from Site Manager /v1/hosts."""
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        response = await client.get(f"{BASE_URL}/v1/hosts", headers=_auth_headers(api_key))
    if response.status_code >= 400:
        raise RuntimeError(f"Site Manager /v1/hosts returned HTTP {response.status_code}.")
    payload = response.json()
    hosts = []
    for i, row in enumerate(_extract_rows(payload)):
        normalized = _normalize_host(row, i)
        if normalized and normalized["hostId"]:
            hosts.append(normalized)
    return hosts


async def get_host(api_key: str, host_id: str) -> dict:
    """Return normalized detail for a single Site Manager host."""
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        response = await client.get(f"{BASE_URL}/v1/hosts/{host_id}", headers=_auth_headers(api_key))
    if response.status_code >= 400:
        raise RuntimeError(f"Site Manager /v1/hosts/{host_id} returned HTTP {response.status_code}.")
    payload = response.json()
    row = payload.get("data", payload) if isinstance(payload, dict) else payload
    normalized = _normalize_host(row)
    if not normalized:
        raise RuntimeError(f"Could not parse host response for {host_id}.")
    return normalized

from __future__ import annotations

import httpx

_update: dict | None = None
_checked = False


def get_cached_update() -> dict | None:
    return _update


async def check_for_update(current_version: str) -> None:
    global _update, _checked
    if _checked:
        return
    _checked = True
    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
            response = await client.get(
                "https://api.github.com/repos/aniceberg/Blink/releases/latest",
                headers={"Accept": "application/vnd.github+json"},
            )
        if response.status_code != 200:
            return
        data = response.json()
        tag = (data.get("tag_name") or "").lstrip("v")
        url = data.get("html_url") or ""
        if tag and tag != current_version and _is_newer(tag, current_version):
            _update = {"tag_name": data["tag_name"], "html_url": url}
    except Exception:
        pass


def _is_newer(latest: str, current: str) -> bool:
    def parts(v: str) -> tuple[int, ...]:
        try:
            return tuple(int(x) for x in v.split("."))
        except ValueError:
            return (0,)

    return parts(latest) > parts(current)

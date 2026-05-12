from __future__ import annotations

import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

import uvicorn
import webview

from app.main import app as blink_app


class BlinkApi:
    def __init__(self) -> None:
        self.window = None

    def select_output_directory(self, current_path: str | None = None) -> str | None:
        if self.window is None:
            return None
        directory = ""
        if current_path:
            expanded = Path(current_path).expanduser()
            directory = str(expanded if expanded.is_dir() else expanded.parent)
        file_dialog = getattr(webview, "FileDialog", None)
        dialog_type = file_dialog.FOLDER if file_dialog else webview.FOLDER_DIALOG
        selected = self.window.create_file_dialog(dialog_type, directory=directory, allow_multiple=False)
        if not selected:
            return None
        return str(selected[0])

    def reveal_path(self, path: str) -> bool:
        subprocess.run(["open", "-R", path], check=False)
        return True


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_server(url: str, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1):
                return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError(f"Blink did not start within {timeout:.0f} seconds.")


def main() -> None:
    port = _available_port()
    url = f"http://127.0.0.1:{port}"
    api = BlinkApi()
    server = uvicorn.Server(
        uvicorn.Config(
            blink_app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            access_log=False,
        )
    )
    thread = threading.Thread(target=server.run, name="blink-uvicorn", daemon=True)
    thread.start()

    try:
        _wait_for_server(url)
        api.window = webview.create_window("Blink", url, width=1280, height=900, min_size=(900, 650), js_api=api)
        webview.start()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


if __name__ == "__main__":
    main()

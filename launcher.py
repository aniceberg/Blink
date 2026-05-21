from __future__ import annotations

import socket
import subprocess
import threading
import time
from pathlib import Path

import webview


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


def _wait_for_server(port: int, timeout: float = 15.0) -> bool:
    """Wait for the server to accept connections on the given port.
    Uses a raw socket to bypass system-level HTTP timeouts (like macOS ATS).
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except Exception:
            time.sleep(0.1)
    return False


def main() -> None:
    port = _available_port()
    url = f"http://localhost:{port}"
    api = BlinkApi()

    # Minimum time to show the loading screen so it doesn't flash on fast launches.
    MIN_LOADING_SECONDS = 1.5

    loading_html = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    background: #111;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100vh;
    font-family: -apple-system, BlinkMacSystemFont, sans-serif;
    -webkit-user-select: none;
    user-select: none;
    cursor: default;
  }
  .wordmark {
    font-size: 26px;
    font-weight: 600;
    letter-spacing: 0.08em;
    color: #fff;
    margin-bottom: 28px;
  }
  .ring {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    border: 2.5px solid rgba(255,255,255,0.12);
    border-top-color: rgba(255,255,255,0.7);
    animation: spin 0.75s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>
  <div class="wordmark">Blink</div>
  <div class="ring"></div>
</body>
</html>"""

    # 1. Show the window immediately with the loading screen while the heavy
    #    Python imports and uvicorn startup happen in the background.
    api.window = webview.create_window(
        "Blink",
        html=loading_html,
        width=1280,
        height=900,
        min_size=(900, 650),
        js_api=api,
    )

    def _start_backend():
        started_at = time.monotonic()

        # 2. Perform heavy imports in the background thread.
        import uvicorn
        from app.main import app as blink_app

        server = uvicorn.Server(
            uvicorn.Config(
                blink_app,
                host="127.0.0.1",
                port=port,
                log_level="warning",
                access_log=False,
            )
        )

        # 3. Start the uvicorn server in its own thread.
        server_thread = threading.Thread(target=server.run, name="blink-uvicorn", daemon=True)
        server_thread.start()

        # 4. Wait for the server to be ready, then honour the minimum loading
        #    display time so the screen doesn't flash on fast subsequent launches.
        if _wait_for_server(port):
            elapsed = time.monotonic() - started_at
            remaining = MIN_LOADING_SECONDS - elapsed
            if remaining > 0:
                time.sleep(remaining)
            api.window.load_url(url)

    # 5. Start the GUI loop. The provided function runs in a background thread.
    webview.start(_start_backend)


if __name__ == "__main__":
    main()

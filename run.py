"""Cross-platform launcher that starts the FastAPI server and opens the browser."""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser

import uvicorn

from app import app


def ensure_stdio() -> None:
    """Ensure stdout/stderr exist in windowed PyInstaller builds."""
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


def find_free_port(start_port: int = 8000, max_tries: int = 20) -> int:
    """Find an available localhost port starting from start_port."""
    for port in range(start_port, start_port + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start_port


def open_browser_when_ready(port: int) -> None:
    """Wait until the local server accepts connections, then open the Web UI."""
    url = f"http://127.0.0.1:{port}"
    for _ in range(40):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                webbrowser.open(url)
                return
        time.sleep(0.25)


def main() -> None:
    """Start the uvicorn server and launch the user's default browser."""
    ensure_stdio()
    port = find_free_port(8000)
    print(f"正在啟動 YouTube 下載器：http://127.0.0.1:{port}")
    threading.Thread(target=open_browser_when_ready, args=(port,), daemon=True).start()
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        log_config=None,
        use_colors=False,
    )


if __name__ == "__main__":
    main()

"""GroupThink desktop launcher.

Starts the FastAPI app on a free localhost port in a background thread, then
opens a native window (pywebview) pointed at it. This is the entry point used
by the PyInstaller-built ``GroupThink.app``.

Running from a checkout:
    pip install -r requirements-desktop.txt
    python -m groupthink.desktop
"""

from __future__ import annotations

import socket
import sys
import threading
import time
from contextlib import closing


def find_free_port() -> int:
    """Ask the kernel for a free TCP port on localhost."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_server(port: int, timeout: float = 8.0) -> None:
    """Block until something is accepting on ``port`` (uvicorn is up)."""
    deadline = time.monotonic() + timeout
    last_err: OSError | None = None
    while time.monotonic() < deadline:
        try:
            with closing(socket.create_connection(("127.0.0.1", port), timeout=0.25)):
                return
        except OSError as exc:
            last_err = exc
            time.sleep(0.05)
    raise RuntimeError(f"GroupThink backend didn't come up on port {port} ({last_err})")


def _run_uvicorn(port: int) -> None:
    # Local import: the desktop launcher pulls all of FastAPI in here, so it
    # only runs on the desktop path (not when, say, a test imports this module).
    import uvicorn

    from .web.app import app

    uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    ).run()


def launch(window_size: tuple[int, int] = (1280, 860)) -> int:
    """Start the backend and open the native window. Blocks until window closes."""
    try:
        import webview
    except ImportError as exc:
        raise SystemExit(
            "GroupThink desktop requires pywebview.\n"
            "Install it with:  pip install -r requirements-desktop.txt"
        ) from exc

    port = find_free_port()
    threading.Thread(target=_run_uvicorn, args=(port,), daemon=True).start()
    wait_for_server(port)

    webview.create_window(
        "GroupThink",
        f"http://127.0.0.1:{port}",
        width=window_size[0],
        height=window_size[1],
        min_size=(960, 640),
        resizable=True,
    )
    webview.start()
    return 0


def main() -> int:
    return launch()


if __name__ == "__main__":
    sys.exit(main())

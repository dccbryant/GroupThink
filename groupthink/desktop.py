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
import traceback
from contextlib import closing
from datetime import datetime
from pathlib import Path


# --------------------------------------------------------------------------- #
# Crash logging — silent .app crashes have no console, so write to a log file
# the user can read after the fact.
# --------------------------------------------------------------------------- #


def _log_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "GroupThink"
    return Path.home() / ".groupthink" / "logs"


def _log(label: str, message: str | None = None, exc: BaseException | None = None) -> None:
    try:
        d = _log_dir()
        d.mkdir(parents=True, exist_ok=True)
        with (d / "launch.log").open("a", encoding="utf-8") as f:
            f.write(f"\n=== {datetime.now().isoformat()} {label} ===\n")
            if message:
                f.write(message + "\n")
            if exc is not None:
                traceback.print_exception(type(exc), exc, exc.__traceback__, file=f)
    except Exception:
        # Never let logging itself crash the launcher.
        pass


# --------------------------------------------------------------------------- #
# Backend bring-up
# --------------------------------------------------------------------------- #


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


def _run_uvicorn(port: int, error_box: dict) -> None:
    """Run the FastAPI app on `port`. Surface any error via `error_box`.

    NOTE: this MUST use an absolute import (``from groupthink.web.app``). When
    the launcher is the entry point of a PyInstaller bundle, the script runs
    without a package context, so relative imports fail with "attempted
    relative import with no known parent package".
    """
    try:
        import uvicorn

        from groupthink.web.app import app

        uvicorn.Server(
            uvicorn.Config(
                app, host="127.0.0.1", port=port, log_level="warning", access_log=False
            )
        ).run()
    except BaseException as exc:  # noqa: BLE001 — surface ANY failure
        _log("uvicorn-thread", exc=exc)
        error_box["exc"] = exc


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #


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
    error_box: dict = {}
    server_thread = threading.Thread(
        target=_run_uvicorn, args=(port, error_box), daemon=True
    )
    server_thread.start()

    try:
        wait_for_server(port)
    except RuntimeError as exc:
        # If the uvicorn thread captured a real exception, surface that instead
        # of the "connection refused" symptom.
        inner = error_box.get("exc")
        if inner is not None:
            _log("launch", message="uvicorn never came up — see the traceback above")
            raise inner from exc
        _log("launch", exc=exc)
        raise

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
    try:
        return launch()
    except BaseException as exc:  # noqa: BLE001
        _log("main", exc=exc)
        raise


if __name__ == "__main__":
    sys.exit(main())

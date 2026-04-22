#!/usr/bin/env python3
"""Mini screenshot watcher PoC for ActivityWatch.

Features:
- Captures screenshots on a fixed interval.
- Stores image files on disk.
- Persists heartbeat requests immediately to aw-client's SQLite-backed queue.
- If aw-server is unavailable, samples are still considered scheduled/sent locally and
  will be delivered later when the client can reconnect.

Notes:
- This is a PoC, intended for Linux desktop sessions.
- It tries several screenshot backends in order: gnome-screenshot, grim, scrot, import.
- Event payload contains metadata + file path, not raw image bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import shutil
import signal
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from time import sleep
from typing import Optional

from aw_client import ActivityWatchClient
from aw_core.models import Event

logger = logging.getLogger("mini-screenshot-watcher")

DEFAULT_INTERVAL_MINUTES = 5.0
DEFAULT_EVENT_TYPE = "os.desktop.screenshot"
DEFAULT_CLIENT_NAME = "aw-watcher-screenshot-mini"
DEFAULT_PULSE_TIME = 0.0


class ScreenshotCaptureError(RuntimeError):
    pass


class ScreenshotWatcher:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.running = True
        self.client = ActivityWatchClient(
            DEFAULT_CLIENT_NAME,
            host=args.host,
            port=args.port,
            testing=args.testing,
        )
        self.bucket_id = f"{self.client.client_name}_{self.client.client_hostname}"
        self.output_dir = Path(args.output_dir).expanduser()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.hostname = socket.gethostname()

    def run(self) -> None:
        logger.info("Starting mini screenshot watcher")
        self.client.create_bucket(self.bucket_id, DEFAULT_EVENT_TYPE, queued=True)

        signal.signal(signal.SIGINT, self._handle_stop)
        signal.signal(signal.SIGTERM, self._handle_stop)

        with self.client:
            while self.running:
                event = self.capture_and_build_event()
                self.enqueue_heartbeat(event)
                logger.info("Queued screenshot event: %s", event.data["path"])
                sleep(self.args.interval_seconds)

        logger.info("Watcher stopped")

    def _handle_stop(self, *_args) -> None:
        logger.info("Stop signal received")
        self.running = False

    def capture_and_build_event(self) -> Event:
        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y%m%dT%H%M%S%fZ")
        filename = f"screenshot-{timestamp}.png"
        screenshot_path = self.output_dir / filename

        backend = capture_screenshot(screenshot_path)
        sha256 = sha256sum(screenshot_path)
        file_size = screenshot_path.stat().st_size

        data = {
            "path": str(screenshot_path),
            "sha256": sha256,
            "bytes": file_size,
            "backend": backend,
            "hostname": self.hostname,
            "captured_at": now.isoformat(),
        }

        return Event(timestamp=now, data=data)

    def enqueue_heartbeat(self, event: Event) -> None:
        endpoint = f"buckets/{self.bucket_id}/heartbeat?pulsetime={DEFAULT_PULSE_TIME}"
        self.client.request_queue.add_request(endpoint, event.to_json_dict())


def sha256sum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def capture_screenshot(output_path: Path) -> str:
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        raise ScreenshotCaptureError(
            "No DISPLAY/WAYLAND_DISPLAY found; screenshot capture requires a GUI session"
        )

    backends = [
        ("gnome-screenshot", ["gnome-screenshot", "-f", str(output_path)]),
        ("grim", ["grim", str(output_path)]),
        ("scrot", ["scrot", str(output_path)]),
        ("import", ["import", "-window", "root", str(output_path)]),
    ]

    last_error: Optional[Exception] = None
    for name, command in backends:
        if shutil.which(command[0]) is None:
            continue
        try:
            subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            if output_path.exists() and output_path.stat().st_size > 0:
                return name
        except Exception as exc:
            last_error = exc
            logger.warning("Screenshot backend '%s' failed: %s", name, exc)

    raise ScreenshotCaptureError(
        "No working screenshot backend found"
        + (f": {last_error}" if last_error else "")
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture screenshots periodically and enqueue ActivityWatch heartbeat events."
    )
    parser.add_argument("--host", default=None, help="aw-server host")
    parser.add_argument("--port", type=int, default=None, help="aw-server port")
    parser.add_argument(
        "--testing",
        action="store_true",
        help="Use ActivityWatch testing mode (default test server port 5666)",
    )
    parser.add_argument(
        "--interval-minutes",
        type=float,
        default=DEFAULT_INTERVAL_MINUTES,
        help="Capture interval in minutes",
    )
    parser.add_argument(
        "--output-dir",
        default="~/.local/share/activitywatch/screenshots-mini",
        help="Directory where screenshots are stored",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()
    args.interval_seconds = max(args.interval_minutes * 60.0, 1.0)
    return args


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    watcher = ScreenshotWatcher(args)
    watcher.run()


if __name__ == "__main__":
    main()

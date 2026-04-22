from __future__ import annotations

import hashlib
import logging
import signal
import socket
from datetime import datetime, timezone
from pathlib import Path
from time import sleep

from aw_client import ActivityWatchClient
from aw_core.models import Event

from .capture import capture_screenshot
from .config import DEFAULT_CLIENT_NAME, DEFAULT_EVENT_TYPE, DEFAULT_PULSE_TIME, parse_args

logger = logging.getLogger(__name__)


class ScreenshotWatcher:
    def __init__(self, args) -> None:
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
        logger.info("Starting screenshot watcher")
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
        screenshot_path = self.output_dir / f"screenshot-{timestamp}.bmp"

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


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    ScreenshotWatcher(args).run()

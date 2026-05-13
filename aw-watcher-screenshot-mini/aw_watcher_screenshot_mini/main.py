from __future__ import annotations

import hashlib
import logging
import os
import signal
import socket
import sys
from dataclasses import asdict
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import sleep
from typing import Any, Dict, List, Optional

from aw_client import ActivityWatchClient
from aw_client.odoo_config import apply_global_odoo_config
from aw_core.dirs import get_log_dir
from aw_core.models import Event

from PIL import Image

from .capture import ScreenshotTransientError, capture_screenshots, load_image
from .config import DEFAULT_CLIENT_NAME, DEFAULT_EVENT_TYPE, AppConfig, LoggingConfig, parse_args
from .odoo_client import OdooActivityTrackingClient, OdooPushConfig

logger = logging.getLogger(__name__)

_IDLE_POLL_SECS = 30.0


def _default_log_dir() -> Path:
    env_log_dir = os.getenv("AW_LOG_DIR")
    if env_log_dir:
        return Path(env_log_dir).expanduser()
    env_log_root = os.getenv("AW_LOG_ROOT")
    if env_log_root:
        return Path(env_log_root).expanduser() / DEFAULT_CLIENT_NAME
    if getattr(sys, "frozen", False):
        return Path(get_log_dir(DEFAULT_CLIENT_NAME))
    return Path(get_log_dir(DEFAULT_CLIENT_NAME))


def _resolve_log_level(verbose: bool, config_level: str) -> int:
    if verbose:
        return logging.DEBUG
    env_level = os.getenv("LOG_LEVEL") or os.getenv("AW_LOG_LEVEL")
    candidate = (env_level or config_level or "INFO").upper()
    return getattr(logging, candidate, logging.INFO)


def _resolve_log_dir(config: LoggingConfig) -> Path:
    if config.dir:
        return Path(config.dir).expanduser()
    env_dir = os.getenv("AW_LOG_DIR")
    if env_dir:
        return Path(env_dir).expanduser()
    return _default_log_dir()


def _resolve_log_filename(config: LoggingConfig) -> str:
    if config.filename.strip():
        return config.filename.strip()
    now_str = datetime.now().replace(microsecond=0).isoformat().replace(":", "-")
    return f"aw-watcher-screenshot-mini_{now_str}.log"


def _configure_logging(verbose: bool, config: LoggingConfig) -> Optional[Path]:
    if not config.enabled:
        return None

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    level = _resolve_log_level(verbose, config.level)
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()

    if config.to_stdout:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    log_dir = _resolve_log_dir(config)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / _resolve_log_filename(config)

    if config.to_file:
        file_handler = TimedRotatingFileHandler(
            log_path,
            when=config.rotate_when or "midnight",
            interval=max(int(config.rotate_interval or 1), 1),
            backupCount=max(int(config.backup_count or 0), 0),
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    logging.captureWarnings(True)
    return log_path


def _install_exception_logging() -> None:
    def _handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logging.getLogger(__name__).critical(
            "Unhandled exception caused watcher termination",
            exc_info=(exc_type, exc_value, exc_traceback),
        )

    sys.excepthook = _handle_exception


def _mask_secret(value: Optional[str], visible: int = 4) -> str:
    if not value:
        return ""
    if visible <= 0:
        return "*" * len(value)
    if len(value) <= visible:
        return "*" * len(value)
    return "*" * (len(value) - visible) + value[-visible:]


def _log_startup_config(config: AppConfig, log_path: Optional[Path]) -> None:
    logger.info("Watcher config path: %s", config.config_path or "<default>")
    if log_path:
        logger.info("Log file: %s", log_path)
    logger.info(
        "Logging config: enabled=%s dir=%s level=%s to_stdout=%s to_file=%s rotate_when=%s rotate_interval=%s backup_count=%s filename=%s",
        config.logging.enabled,
        config.logging.dir or "<default>",
        config.logging.level,
        config.logging.to_stdout,
        config.logging.to_file,
        config.logging.rotate_when,
        config.logging.rotate_interval,
        config.logging.backup_count,
        config.logging.filename or "<default>",
    )
    logger.info(
        "AW server: host=%s port=%s bucket_id=%s pulse_time=%s timeout_secs=%s event_type=%s api_path=%s sync_enabled=%s",
        config.aw_server.host,
        config.aw_server.port,
        config.aw_server.bucket_id,
        config.aw_server.pulse_time,
        config.aw_server.timeout_secs,
        config.aw_server.event_type,
        config.aw_server.api_path or "",
        config.aw_server.sync_enabled,
    )
    logger.info(
        "Capture: interval_secs=%s force_interval_secs=%s dhash_threshold=%s",
        config.trigger.interval_secs,
        config.capture.force_interval_secs,
        config.capture.dhash_threshold,
    )
    logger.info(
        "Cache: dir=%s webp_quality=%s max_width=%s max_height=%s cleanup_after_hours=%s cleanup_every_n_captures=%s",
        config.cache.cache_dir,
        config.cache.webp_quality,
        config.cache.max_width,
        config.cache.max_height,
        config.cache.cleanup_after_hours,
        config.cache.cleanup_every_n_captures,
    )
    logger.info(
        "Odoo: enabled=%s base_url=%s pin_code=%s token=%s api_secret=%s sign_requests=%s employee_id=%s device_id=%s device_name=%s timeout_secs=%s push_screenshots=%s push_metadata_events=%s",
        config.odoo.enabled,
        config.odoo.base_url,
        _mask_secret(config.odoo.pin_code),
        _mask_secret(config.odoo.token),
        _mask_secret(config.odoo.api_secret),
        config.odoo.sign_requests,
        config.odoo.employee_id,
        config.odoo.device_id,
        config.odoo.device_name,
        config.odoo.timeout_secs,
        config.odoo.push_screenshots,
        config.odoo.push_metadata_events,
    )


class ScreenshotWatcher:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.running = True
        self.client = ActivityWatchClient(
            DEFAULT_CLIENT_NAME,
            host=config.aw_server.host,
            port=config.aw_server.port,
            testing=config.testing,
        )
        self.bucket_id = config.aw_server.bucket_id or f"{self.client.client_name}_{self.client.client_hostname}"
        self.output_dir = Path(config.cache.cache_dir).expanduser()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.hostname = config.aw_server.hostname or socket.gethostname()
        self.last_hash: Optional[int] = None
        self.last_capture_ts: Optional[datetime] = None
        self.last_event_data: Optional[Dict[str, Any]] = None
        self.last_event_ts: Optional[datetime] = None
        self.last_monitor_hashes: Dict[str, int] = {}
        self.capture_count = 0
        self.s3_client = self._build_s3_client()
        self.capture_failures = 0
        self.last_capture_error: Optional[str] = None
        self.last_remote_config: Optional[Dict[str, Any]] = None
        self._warned_remote_unavailable = False
        self.odoo_client = OdooActivityTrackingClient(
            OdooPushConfig(**vars(config.odoo)),
            agent_version="aw-watcher-screenshot-mini/0.1.0",
        )

    def run(self) -> None:
        logger.info("Starting screenshot watcher")
        signal.signal(signal.SIGINT, self._handle_stop)
        signal.signal(signal.SIGTERM, self._handle_stop)

        try:
            self.client.wait_for_start()
            self.client.create_bucket(self.bucket_id, DEFAULT_EVENT_TYPE, queued=True)
        except Exception:
            logger.exception("Unable to connect to aw-server or create screenshot bucket; watcher will stop")
            return

        self._refresh_odoo_config()
        self.odoo_client.start()

        with self.client:
            while self.running:
                tracking_config = self._get_tracking_config()
                cycle_time_secs = tracking_config["cycle_time_secs"]
                if not tracking_config["is_tracking"] or not tracking_config["is_tracking_screenshot"]:
                    self._sleep_with_heartbeat(_IDLE_POLL_SECS, send_heartbeat=False)
                    continue
                if not tracking_config["is_working"]:
                    self._sleep_with_heartbeat(_IDLE_POLL_SECS, send_heartbeat=False)
                    continue

                self._capture_once(tracking_config)
                slot_duration = cycle_time_secs / tracking_config["screenshot_per_cycle"]
                self._sleep_with_heartbeat(slot_duration, send_heartbeat=True)

        logger.info("Watcher stopped")
        self.odoo_client.stop()

    def _handle_stop(self, *_args) -> None:
        logger.info("Stop signal received")
        self.running = False

    def _capture_once(self, tracking_context: Optional[Dict[str, Any]] = None) -> None:
        try:
            event = self.capture_and_build_event()
            if event is not None:
                self._mark_capture_recovered()
                self.enqueue_heartbeat(event)
                self.odoo_client.push_screenshot_event(event.data, tracking_context=tracking_context)
                image_count = event.data.get("image_count", 0)
                first_path = None
                images = event.data.get("images", [])
                if images and isinstance(images, list):
                    first_path = images[0].get("path")

                if first_path:
                    logger.info(
                        "Queued screenshot event: %s image(s), first=%s",
                        image_count,
                        first_path,
                    )
                else:
                    logger.info("Queued screenshot event: %s image(s)", image_count)
            else:
                self._mark_capture_recovered()
                self.enqueue_last_heartbeat()
        except ScreenshotTransientError as exc:
            self._record_capture_failure(exc)
            logger.warning("Desktop capture temporarily unavailable: %s", exc)
            self.enqueue_last_heartbeat()
        except Exception:
            logger.exception("Capture loop iteration failed")

    def _get_tracking_config(self) -> Dict[str, Any]:
        self._refresh_odoo_config()
        fallback_cycle_secs = max(float(self.config.trigger.interval_secs or 60.0), 1.0)
        fallback = {
            "is_tracking": False,
            "is_tracking_idle": False,
            "is_tracking_screenshot": False,
            "is_working": False,
            "timer_session_id": False,
            "account_analytic_line_id": False,
            "task_id": False,
            "task_name": False,
            "started_at": False,
            "screenshot_per_cycle": 1,
            "cycle_time_secs": fallback_cycle_secs,
        }
        if not self.odoo_client.enabled:
            logger.warning("Odoo sync disabled; using fallback tracking config")
            return fallback

        remote = self.odoo_client.get_tracking_config()
        if not remote:
            if not self._warned_remote_unavailable:
                logger.warning("Remote tracking config unavailable; using fallback config")
                self._warned_remote_unavailable = True
            return fallback

        if self._warned_remote_unavailable:
            logger.info("Remote tracking config available again")
            self._warned_remote_unavailable = False

        screenshot_per_cycle = int(remote.get("screenshot_per_cycle") or 0)
        cycle_time_secs = int(remote.get("cycle_time_secs") or 0)
        if cycle_time_secs <= 0:
            cycle_time_minutes = int(remote.get("cycle_time") or 0)
            cycle_time_secs = cycle_time_minutes * 60

        if screenshot_per_cycle <= 0:
            screenshot_per_cycle = 1
        if cycle_time_secs <= 0:
            cycle_time_secs = int(fallback_cycle_secs)

        resolved = {
            "is_tracking": bool(remote.get("is_tracking", False)),
            "is_tracking_idle": bool(remote.get("is_tracking_idle", False)),
            "is_tracking_screenshot": bool(remote.get("is_tracking_screenshot", False)),
            "is_working": bool(remote.get("is_working", False)),
            "timer_session_id": remote.get("timer_session_id") or False,
            "account_analytic_line_id": remote.get("account_analytic_line_id") or False,
            "task_id": remote.get("task_id") or False,
            "task_name": remote.get("task_name") or False,
            "started_at": remote.get("started_at") or False,
            "screenshot_per_cycle": screenshot_per_cycle,
            "cycle_time_secs": cycle_time_secs,
        }

        if self.last_remote_config != resolved:
            logger.info("Remote tracking config in use: %s", resolved)
            self.last_remote_config = dict(resolved)

        return resolved

    def _refresh_odoo_config(self) -> None:
        changed = apply_global_odoo_config(
            self.config.odoo,
            self.client,
            logger=logger,
            source=DEFAULT_CLIENT_NAME,
        )
        if not changed:
            return
        self.odoo_client.stop()
        self.odoo_client = OdooActivityTrackingClient(
            OdooPushConfig(**asdict(self.config.odoo)),
            agent_version="aw-watcher-screenshot-mini/0.1.0",
        )
        self.odoo_client.start()

    def _sleep_with_heartbeat(self, total_secs: float, send_heartbeat: bool) -> None:
        if total_secs <= 0:
            return
        tick = self._heartbeat_tick_secs()
        remaining = total_secs
        while remaining > 0 and self.running:
            self._refresh_odoo_config()
            sleep_time = min(tick, remaining)
            if send_heartbeat:
                self.enqueue_last_heartbeat()
            sleep(sleep_time)
            remaining -= sleep_time

    def _heartbeat_tick_secs(self) -> float:
        pulse_time = float(self.config.aw_server.pulse_time or 60.0)
        return max(5.0, min(30.0, pulse_time / 4.0))

    def capture_and_build_event(self) -> Optional[Event]:
        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y%m%dT%H%M%S%fZ")
        cache_dir = self.output_dir / now.strftime("%Y/%m/%d/%H")
        cache_dir.mkdir(parents=True, exist_ok=True)
        backend, screenshots = capture_screenshots(cache_dir, timestamp)

        images_payload: List[Dict[str, Any]] = []
        changed = False

        for monitor_id, screenshot_path in screenshots.items():
            image = load_image(screenshot_path)
            dhash_value = dhash(image)

            if self._should_skip_monitor(now, monitor_id, dhash_value):
                logger.info("Skipping unchanged screenshot for %s", monitor_id)
                screenshot_path.unlink(missing_ok=True)
                continue

            changed = True
            image = self._enhance_for_storage(image)
            webp_path = cache_dir / f"screenshot-{timestamp}-{monitor_id}.webp"
            image.save(
                webp_path,
                format="WEBP",
                quality=self.config.cache.webp_quality,
                method=self.config.cache.webp_method,
                optimize=True,
            )
            screenshot_path.unlink(missing_ok=True)

            sha256 = sha256sum(webp_path)
            file_size = webp_path.stat().st_size
            s3_key = self._upload_to_s3(webp_path)

            images_payload.append(
                {
                    "monitor_id": monitor_id,
                    "path": str(webp_path),
                    "relative_path": str(webp_path.relative_to(self.output_dir)),
                    "sha256": sha256,
                    "bytes": file_size,
                    "dhash": dhash_value,
                    "s3_key": s3_key,
                    "uploaded": bool(s3_key),
                }
            )
            self.last_monitor_hashes[monitor_id] = dhash_value

        if not changed:
            logger.info("Skipping unchanged screenshot")
            return None

        data = {
            "backend": backend,
            "hostname": self.hostname,
            "captured_at": now.isoformat(),
            "local_dir": str(cache_dir),
            "images": images_payload,
            "image_count": len(images_payload),
        }

        self.last_capture_ts = now
        self.last_event_data = data
        self.last_event_ts = now
        self.capture_count += 1
        self._cleanup_cache_if_needed(now)
        return Event(timestamp=now, data=data)

    def enqueue_heartbeat(self, event: Event) -> None:
        if not self.config.aw_server.sync_enabled:
            return

        if self.config.aw_server.api_path:
            self.client.request_queue.add_request(self.config.aw_server.api_path, event.to_json_dict())
            return

        endpoint = f"buckets/{self.bucket_id}/heartbeat?pulsetime={self.config.aw_server.pulse_time}"
        self.client.request_queue.add_request(endpoint, event.to_json_dict())

    def enqueue_last_heartbeat(self) -> None:
        if self.last_event_data is None or self.last_event_ts is None:
            return

        timeout_secs = self.config.aw_server.timeout_secs or self.config.aw_server.pulse_time or 60.0
        if (datetime.now(timezone.utc) - self.last_event_ts) > timedelta(seconds=timeout_secs):
            return

        event = Event(timestamp=self.last_event_ts, data=dict(self.last_event_data))
        self.enqueue_heartbeat(event)

    def _should_skip_monitor(self, now: datetime, monitor_id: str, dhash_value: int) -> bool:
        last_hash = self.last_monitor_hashes.get(monitor_id)
        if self.last_capture_ts is None or last_hash is None:
            return False

        elapsed = (now - self.last_capture_ts).total_seconds()
        if elapsed >= self.config.capture.force_interval_secs:
            return False

        return hamming_distance(dhash_value, last_hash) < self.config.capture.dhash_threshold

    def _enhance_for_storage(self, image: Image.Image) -> Image.Image:
        result = image.convert("RGB")

        max_width = self.config.cache.max_width
        max_height = self.config.cache.max_height
        if max_width or max_height:
            target = (
                max_width or result.width,
                max_height or result.height,
            )
            result.thumbnail(target, Image.Resampling.LANCZOS)

        return result

    def _build_s3_client(self):
        if not self.config.s3.enabled:
            return None

        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError("S3 enabled but boto3 is not installed") from exc

        return boto3.client(
            "s3",
            endpoint_url=self.config.s3.endpoint or None,
            aws_access_key_id=self.config.s3.access_key or None,
            aws_secret_access_key=self.config.s3.secret_key or None,
            region_name=self.config.s3.region or None,
        )

    def _upload_to_s3(self, path: Path) -> Optional[str]:
        if self.s3_client is None:
            return None

        key_prefix = self.config.s3.key_prefix.strip("/")
        key = f"{key_prefix + '/' if key_prefix else ''}{path.name}"
        self.s3_client.upload_file(str(path), self.config.s3.bucket, key)
        return key

    def _cleanup_cache_if_needed(self, now: datetime) -> None:
        if self.config.cache.cleanup_after_hours is None:
            return
        # Skip cleanup if Odoo sync is enabled to prevent deletion of files before they're pushed
        if self.config.odoo.enabled:
            logger.debug("Skipping cache cleanup because Odoo sync is enabled")
            return
        if self.capture_count % max(self.config.cache.cleanup_every_n_captures, 1) != 0:
            return

        cutoff = now - timedelta(hours=self.config.cache.cleanup_after_hours)
        for path in self.output_dir.rglob("*.webp"):
            try:
                modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                if modified < cutoff:
                    path.unlink(missing_ok=True)
            except OSError:
                logger.warning("Failed to cleanup cache file: %s", path)

        for directory in sorted(self.output_dir.rglob("*"), reverse=True):
            if directory.is_dir():
                try:
                    next(directory.iterdir())
                except StopIteration:
                    directory.rmdir()
                except OSError:
                    continue

    def _record_capture_failure(self, exc: Exception) -> None:
        self.capture_failures += 1
        self.last_capture_error = str(exc)

    def _mark_capture_recovered(self) -> None:
        if self.capture_failures > 0:
            logger.info(
                "Desktop capture recovered after %s transient failure(s)%s",
                self.capture_failures,
                f": {self.last_capture_error}" if self.last_capture_error else "",
            )
            self.capture_failures = 0
            self.last_capture_error = None


def sha256sum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dhash(image: Image.Image) -> int:
    resized = image.convert("L").resize((9, 8))
    pixels = list(resized.getdata())
    value = 0
    for row in range(8):
        for col in range(8):
            left = pixels[row * 9 + col]
            right = pixels[row * 9 + col + 1]
            if left < right:
                value |= 1 << (row * 8 + col)
    return value


def hamming_distance(left: int, right: int) -> int:
    value = left ^ right
    return value.bit_count() if hasattr(value, "bit_count") else bin(value).count("1")


def main() -> None:
    config = parse_args()
    log_path = _configure_logging(config.verbose, config.logging)
    _install_exception_logging()
    if log_path:
        logger.info("Logging initialized at %s", log_path)
    _log_startup_config(config, log_path)
    ScreenshotWatcher(config).run()

from __future__ import annotations

import hashlib
import json
import logging
import random
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from time import sleep
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from aw_client import ActivityWatchClient
from aw_client.odoo_config import apply_global_odoo_config
try:
    from aw_client.odoo_config import ODOO_TRACKING_CONTEXT_SETTING
except ImportError:
    ODOO_TRACKING_CONTEXT_SETTING = "odoo_tracking_context"
from aw_core.models import Event

from .config import AppConfig, resolve_state_path
from .odoo_client import OdooActivityTrackingClient, OdooPushConfig

logger = logging.getLogger(__name__)

MIN_SCREENSHOT_CYCLE_SECS = 60
MAX_SCREENSHOT_CYCLE_SECS = 3540

KNOWN_BUCKET_TYPES_BY_PREFIX = {
    "aw-watcher-input_": "os.hid.input",
    "aw-watcher-window_": "currentwindow",
    "aw-watcher-afk_": "afkstatus",
    "aw-watcher-screenshot-mini": "os.desktop.screenshot",
}


@dataclass
class BucketSyncCursor:
    last_timestamp: str


class SyncState:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.buckets: Dict[str, BucketSyncCursor] = {}
        self.attachments: Set[str] = set()
        self.screenshot_targets: Set[str] = set()
        self._load()

    def get_last_timestamp(self, bucket_id: str) -> Optional[datetime]:
        cursor = self.buckets.get(bucket_id)
        if not cursor:
            return None
        return _parse_datetime(cursor.last_timestamp)

    def set_last_timestamp(self, bucket_id: str, timestamp: datetime) -> None:
        self.buckets[bucket_id] = BucketSyncCursor(last_timestamp=timestamp.astimezone(timezone.utc).isoformat())

    def has_attachment(self, attachment_id: str) -> bool:
        return attachment_id in self.attachments

    def add_attachment(self, attachment_id: str) -> None:
        self.attachments.add(attachment_id)

    def has_screenshot_target(self, target_key: str) -> bool:
        return target_key in self.screenshot_targets

    def add_screenshot_target(self, target_key: str) -> None:
        self.screenshot_targets.add(target_key)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "buckets": {bucket_id: asdict(cursor) for bucket_id, cursor in self.buckets.items()},
            "attachments": sorted(self.attachments),
            "screenshot_targets": sorted(self.screenshot_targets),
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Failed to read sync state file: %s", self.path)
            return
        self.buckets = {
            bucket_id: BucketSyncCursor(**cursor)
            for bucket_id, cursor in (payload.get("buckets") or {}).items()
        }
        self.attachments = set(payload.get("attachments") or [])
        self.screenshot_targets = set(payload.get("screenshot_targets") or [])


class ActivityWatchOdooSyncService:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.client = ActivityWatchClient(
            "aw-odoo-sync",
            host=config.server.host,
            port=config.server.port,
        )
        self.odoo_client = OdooActivityTrackingClient(
            OdooPushConfig(**asdict(config.odoo)),
            agent_version="aw-odoo-sync/0.1.0",
        )
        self.state = SyncState(resolve_state_path(config))
        self.running = True
        self.last_tracking_context: Optional[Dict[str, Any]] = None
        self.last_tracking_context_fingerprint: Optional[str] = None
        self.warned_tracking_context_unavailable = False
        self.warned_odoo_disabled = False

    def run_forever(self) -> None:
        logger.info("Starting aw-odoo-sync")
        self.client.wait_for_start()
        self.client.connect()
        self._refresh_odoo_config()
        self.odoo_client.start()
        try:
            while self.running:
                self.sync_once()
                sleep(self.config.server.poll_interval_secs)
        finally:
            self.client.disconnect()
            self.state.save()

    def sync_once(self) -> None:
        self._refresh_odoo_config()
        tracking_context = self._refresh_tracking_context()
        if tracking_context is None:
            self.state.save()
            return
        buckets = self.client.get_buckets()
        for bucket_id, bucket in buckets.items():
            bucket_type = self._resolve_bucket_type(bucket_id, bucket)
            is_screenshot_bucket = self._is_screenshot_bucket(bucket_id, bucket_type)
            if is_screenshot_bucket:
                if self._should_sync_bucket_now(bucket_type, tracking_context, is_screenshot_bucket=True):
                    self._sync_screenshot_bucket(bucket_id, bucket_type, tracking_context)
                else:
                    self._discard_bucket_events(bucket_id, "tracking policy inactive")
                continue
            if not self._should_sync_bucket_type(bucket_type):
                continue
            if self._should_sync_bucket_now(bucket_type, tracking_context):
                self._sync_bucket_events(bucket_id, bucket_type, tracking_context)
            else:
                self._discard_bucket_events(bucket_id, "tracking policy inactive")
        self.state.save()

    def _sync_bucket_events(self, bucket_id: str, bucket_type: str, tracking_context: Dict[str, Any]) -> None:
        synced_events = 0
        skipped_events = 0
        while True:
            events = self._get_bucket_events(bucket_id)
            if not events:
                return
            payload_events = [self._serialize_event(bucket_id, event) for event in events]
            policy_events = [
                event
                for event in payload_events
                if self._should_sync_event(bucket_type, event, tracking_context)
            ]
            syncable_events = self.odoo_client.filter_syncable_events(policy_events)
            if not syncable_events:
                skipped_events += len(events)
                self._advance_cursor(bucket_id, events)
            else:
                result = self.odoo_client.push_bucket_events(
                    bucket_id,
                    bucket_type,
                    syncable_events,
                    tracking_context=tracking_context,
                )
                if result is None:
                    return
                synced_events += len(syncable_events)
                skipped_events += len(events) - len(syncable_events)
                self._advance_cursor(bucket_id, events)

            if len(events) < self.config.server.batch_size:
                logger.info(
                    "Synced %s events from %s (%s skipped by policy)",
                    synced_events,
                    bucket_id,
                    skipped_events,
                )
                return

    def _sync_screenshot_bucket(self, bucket_id: str, bucket_type: str, tracking_context: Dict[str, Any]) -> None:
        if not self.config.screenshot.enabled:
            self._discard_bucket_events(bucket_id, "screenshot sync disabled")
            return
        now = datetime.now(timezone.utc)
        started_at = _parse_optional_datetime(tracking_context.get("started_at"))
        if started_at is not None and now < started_at:
            return

        uploaded_attachments = 0
        checked_targets = 0
        cycle_time_secs = _normalize_screenshot_cycle_secs(
            tracking_context.get("cycle_time_secs"),
            default=600,
            warn=False,
        )
        selection_window = max(int(self.config.screenshot.selection_window_secs or 0), 0)
        local_tz = _device_local_timezone()

        for cycle_start_local in _wall_clock_cycle_starts(now, cycle_time_secs, local_tz):
            cycle_end_local = cycle_start_local + timedelta(seconds=cycle_time_secs)
            cycle_start = cycle_start_local.astimezone(timezone.utc)
            cycle_end = cycle_end_local.astimezone(timezone.utc)
            events = self._get_screenshot_events(bucket_id, cycle_start, min(now, cycle_end))
            targets = _screenshot_target_times(
                tracking_context,
                cycle_start_local,
                bucket_id=bucket_id,
                device_id=self.odoo_client.device_id,
            )
            logger.debug(
                "Screenshot wall-clock targets for %s cycle %s: %s",
                bucket_id,
                cycle_start_local.isoformat(),
                [target.isoformat() for target in targets],
            )
            for target_at in targets:
                if target_at > now:
                    continue
                target_key = _screenshot_target_key(
                    bucket_id,
                    self.odoo_client.device_id,
                    cycle_start_local,
                    target_at,
                )
                if self.state.has_screenshot_target(target_key):
                    continue
                if started_at is not None and target_at < started_at:
                    self.state.add_screenshot_target(target_key)
                    continue
                checked_targets += 1
                event = _select_screenshot_event(events, target_at, selection_window)
                if event is None:
                    if now >= cycle_end + timedelta(seconds=selection_window):
                        self.state.add_screenshot_target(target_key)
                    continue

                uploaded_for_target, target_complete = self._upload_screenshot_event(
                    bucket_id,
                    bucket_type,
                    event,
                    tracking_context,
                )
                uploaded_attachments += uploaded_for_target
                if target_complete:
                    self.state.add_screenshot_target(target_key)

        if checked_targets or uploaded_attachments:
            logger.info(
                "Checked %s screenshot target(s), uploaded %s attachment(s) from %s",
                checked_targets,
                uploaded_attachments,
                bucket_id,
            )

    def _get_screenshot_events(self, bucket_id: str, start: datetime, end: datetime) -> List[Event]:
        events = self.client.get_events(
            bucket_id,
            limit=self.config.server.batch_size,
            start=start,
            end=end,
        )
        return sorted(events, key=lambda event: event.timestamp)

    def _upload_screenshot_event(
        self,
        bucket_id: str,
        bucket_type: str,
        event: Event,
        tracking_context: Dict[str, Any],
    ) -> Tuple[int, bool]:
        images = (event.data or {}).get("images") or []
        captured_at = (event.data or {}).get("captured_at") or event.timestamp.astimezone(timezone.utc).isoformat()
        uploadable_images: List[Tuple[Dict[str, Any], str]] = []
        for image in images:
            if not isinstance(image, dict):
                continue
            attachment_id = _screenshot_attachment_id(image, captured_at)
            if not attachment_id or self.state.has_attachment(attachment_id):
                continue
            path_value = image.get("path")
            if not path_value or not Path(str(path_value)).exists():
                logger.warning("Skipping screenshot attachment with missing file: %s", path_value or "<missing path>")
                continue
            uploadable_images.append((image, attachment_id))

        if not uploadable_images:
            return 0, True

        uploaded = 0
        failed = False
        for image, attachment_id in uploadable_images:
            result = self.odoo_client.push_screenshot_attachment(
                bucket_id,
                bucket_type,
                captured_at,
                image,
                tracking_context=tracking_context,
            )
            if result is None:
                failed = True
                continue
            uploaded += 1
            self.state.add_attachment(attachment_id)
        return uploaded, not failed

    def _get_bucket_events(self, bucket_id: str) -> List[Event]:
        start = self.state.get_last_timestamp(bucket_id)
        if start is None:
            start = datetime.now(timezone.utc) - timedelta(seconds=self.config.server.lookback_secs)
        else:
            start = start + timedelta(milliseconds=1)
        events = self.client.get_events(bucket_id, limit=self.config.server.batch_size, start=start)
        return sorted(events, key=lambda event: event.timestamp)

    def _advance_cursor(self, bucket_id: str, events: List[Event]) -> None:
        if not events:
            return
        last_timestamp = max(event.timestamp for event in events)
        self.state.set_last_timestamp(bucket_id, last_timestamp)

    def _serialize_event(self, bucket_id: str, event: Event) -> Dict[str, Any]:
        data = dict(event.data or {})
        data.setdefault("bucket", bucket_id)
        event_id = _stable_event_id(bucket_id, event, data)
        return {
            "id": event_id,
            "timestamp": event.timestamp.astimezone(timezone.utc).isoformat(),
            "duration": event.duration.total_seconds(),
            "data": data,
        }

    def _refresh_tracking_context(self) -> Optional[Dict[str, Any]]:
        if not self.odoo_client.enabled:
            self.last_tracking_context = None
            self._publish_tracking_context(None)
            self.warned_tracking_context_unavailable = False
            if not self.warned_odoo_disabled:
                logger.info("Odoo sync is disabled; skipping tracking context fetch")
                self.warned_odoo_disabled = True
            return None

        self.warned_odoo_disabled = False
        remote_context = self.odoo_client.get_tracking_config()
        if remote_context is None:
            self.last_tracking_context = None
            self._publish_tracking_context(None)
            if not self.warned_tracking_context_unavailable:
                logger.warning("Odoo tracking context unavailable; skipping sync until it recovers")
                self.warned_tracking_context_unavailable = True
            return None

        tracking_context = _normalize_tracking_context(remote_context)
        self.last_tracking_context = tracking_context
        self._publish_tracking_context(tracking_context)
        if self.warned_tracking_context_unavailable:
            logger.info("Odoo tracking context available again")
            self.warned_tracking_context_unavailable = False

        fingerprint = json.dumps(tracking_context, sort_keys=True, default=str)
        if fingerprint != self.last_tracking_context_fingerprint:
            logger.info("Odoo tracking context in use: %s", tracking_context)
            self.last_tracking_context_fingerprint = fingerprint
        return tracking_context

    def _publish_tracking_context(self, tracking_context: Optional[Dict[str, Any]]) -> None:
        payload = {
            "source": "aw-odoo-sync",
            "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "data": tracking_context,
        }
        try:
            self.client.set_setting(ODOO_TRACKING_CONTEXT_SETTING, payload)  # type: ignore[arg-type]
        except Exception as exc:
            logger.debug("Unable to publish local Odoo tracking context: %s", exc)

    def _should_sync_bucket_now(
        self,
        bucket_type: str,
        tracking_context: Dict[str, Any],
        is_screenshot_bucket: bool = False,
    ) -> bool:
        if not tracking_context.get("is_working"):
            return False
        if not tracking_context.get("is_tracking"):
            return False
        if is_screenshot_bucket or bucket_type == "os.desktop.screenshot":
            return bool(tracking_context.get("is_tracking_screenshot"))
        return True

    def _should_sync_event(self, bucket_type: str, event: Dict[str, Any], tracking_context: Dict[str, Any]) -> bool:
        started_at = _parse_optional_datetime(tracking_context.get("started_at"))
        event_timestamp = _parse_optional_datetime(event.get("timestamp"))
        if started_at and event_timestamp and event_timestamp < started_at:
            return False
        if bucket_type == "os.hid.input" and _is_idle_input_event(event):
            return bool(tracking_context.get("is_tracking_idle"))
        if bucket_type == "afkstatus" and _is_idle_afk_event(event):
            return bool(tracking_context.get("is_tracking_idle"))
        return True

    def _discard_bucket_events(self, bucket_id: str, reason: str) -> None:
        discarded_events = 0
        while True:
            events = self._get_bucket_events(bucket_id)
            if not events:
                break
            discarded_events += len(events)
            self._advance_cursor(bucket_id, events)
            if len(events) < self.config.server.batch_size:
                break
        if discarded_events:
            logger.info("Discarded %s events from %s (%s)", discarded_events, bucket_id, reason)

    def _should_sync_bucket_type(self, bucket_type: str) -> bool:
        allowlist = self.config.server.bucket_allowlist
        if not allowlist:
            return True
        return any(_bucket_matches(pattern, bucket_type) for pattern in allowlist)

    def _is_screenshot_bucket(self, bucket_id: str, bucket_type: str) -> bool:
        if bucket_type == "os.desktop.screenshot":
            return True
        return any(_bucket_matches(pattern, bucket_id) for pattern in self.config.screenshot.bucket_ids)

    def _resolve_bucket_type(self, bucket_id: str, bucket: Dict[str, Any]) -> str:
        bucket_type = str(bucket.get("type") or "")
        if bucket_type:
            return bucket_type
        for prefix, mapped_type in KNOWN_BUCKET_TYPES_BY_PREFIX.items():
            if bucket_id.startswith(prefix):
                return mapped_type
        return ""

    def _refresh_odoo_config(self) -> None:
        changed = apply_global_odoo_config(
            self.config.odoo,
            self.client,
            logger=logger,
            source="aw-odoo-sync",
        )
        if not changed:
            return
        self.odoo_client.stop()
        self.odoo_client = OdooActivityTrackingClient(
            OdooPushConfig(**asdict(self.config.odoo)),
            agent_version="aw-odoo-sync/0.1.0",
        )
        self.odoo_client.start()


def _bucket_matches(pattern: str, bucket_type: str) -> bool:
    if pattern.endswith("*"):
        return bucket_type.startswith(pattern[:-1])
    return pattern == bucket_type


def _parse_datetime(value: str) -> datetime:
    parsed = _parse_optional_datetime(value)
    if parsed is None:
        raise ValueError(f"Invalid datetime: {value!r}")
    return parsed


def _parse_optional_datetime(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_tracking_context(context: Dict[str, Any]) -> Dict[str, Any]:
    screenshot_per_cycle = _positive_int(context.get("screenshot_per_cycle"), default=1)
    cycle_time_secs = _positive_int(context.get("cycle_time_secs"), default=0)
    if cycle_time_secs <= 0:
        cycle_time_secs = _positive_int(context.get("cycle_time"), default=10) * 60
    cycle_time_secs = _normalize_screenshot_cycle_secs(cycle_time_secs, default=600)

    return {
        "is_tracking": bool(context.get("is_tracking", False)),
        "is_tracking_idle": bool(context.get("is_tracking_idle", False)),
        "is_tracking_screenshot": bool(context.get("is_tracking_screenshot", False)),
        "is_working": bool(context.get("is_working", False)),
        "timer_session_id": context.get("timer_session_id") or False,
        "account_analytic_line_id": context.get("account_analytic_line_id") or False,
        "task_id": context.get("task_id") or False,
        "task_name": context.get("task_name") or False,
        "started_at": context.get("started_at") or False,
        "screenshot_per_cycle": screenshot_per_cycle,
        "cycle_time_secs": cycle_time_secs,
    }


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _normalize_screenshot_cycle_secs(value: Any, default: int = 600, warn: bool = True) -> int:
    raw_value = _positive_int(value, default=default)
    rounded = int((raw_value + 30) // 60) * 60
    normalized = min(max(rounded, MIN_SCREENSHOT_CYCLE_SECS), MAX_SCREENSHOT_CYCLE_SECS)
    if warn and normalized != raw_value:
        logger.warning(
            "Normalized screenshot cycle_time_secs from %s to %s; expected a 60s multiple in [%s, %s]",
            raw_value,
            normalized,
            MIN_SCREENSHOT_CYCLE_SECS,
            MAX_SCREENSHOT_CYCLE_SECS,
        )
    return normalized


def _stable_event_id(bucket_id: str, event: Event, data: Dict[str, Any]) -> str:
    timestamp = event.timestamp.astimezone(timezone.utc).isoformat()
    duration = event.duration.total_seconds()
    fingerprint_payload = {
        "bucket": bucket_id,
        "timestamp": timestamp,
        "duration": duration,
        "data": data,
    }
    digest = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    millis = int(event.timestamp.timestamp() * 1000)
    return f"{bucket_id}-{millis}-{digest}"


def _device_local_timezone() -> tzinfo:
    local_tz = datetime.now().astimezone().tzinfo
    return local_tz or timezone.utc


def _wall_clock_cycle_starts(now: datetime, cycle_time_secs: int, local_tz: tzinfo) -> List[datetime]:
    local_now = now.astimezone(local_tz)
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    seconds_since_midnight = int((local_now - local_midnight).total_seconds())
    current_cycle_offset = (seconds_since_midnight // cycle_time_secs) * cycle_time_secs
    current_cycle_start = local_midnight + timedelta(seconds=current_cycle_offset)
    previous_cycle_start = current_cycle_start - timedelta(seconds=cycle_time_secs)
    return [previous_cycle_start, current_cycle_start]


def _screenshot_target_times(
    tracking_context: Dict[str, Any],
    cycle_start: datetime,
    bucket_id: str,
    device_id: str,
) -> List[datetime]:
    screenshot_per_cycle = _positive_int(tracking_context.get("screenshot_per_cycle"), default=1)
    cycle_time_secs = _normalize_screenshot_cycle_secs(
        tracking_context.get("cycle_time_secs"),
        default=600,
        warn=False,
    )
    minute_count = max(1, cycle_time_secs // 60)
    target_count = min(screenshot_per_cycle, minute_count)
    cycle_start_local = cycle_start if cycle_start.tzinfo else cycle_start.replace(tzinfo=timezone.utc)
    seed_parts = [
        str(device_id or ""),
        str(bucket_id or ""),
        cycle_start_local.date().isoformat(),
        cycle_start_local.isoformat(),
        str(cycle_time_secs),
        str(screenshot_per_cycle),
    ]
    seed = hashlib.sha256("|".join(seed_parts).encode("utf-8")).hexdigest()
    rng = random.Random(int(seed[:16], 16))
    offsets = sorted(rng.sample(range(minute_count), target_count))
    return [(cycle_start_local + timedelta(minutes=offset)).astimezone(timezone.utc) for offset in offsets]


def _screenshot_target_key(
    bucket_id: str,
    device_id: str,
    cycle_start: datetime,
    target_at: datetime,
) -> str:
    cycle_start_local = cycle_start if cycle_start.tzinfo else cycle_start.replace(tzinfo=timezone.utc)
    target_local = target_at.astimezone(cycle_start_local.tzinfo or timezone.utc)
    target_minute = int((target_local - cycle_start_local).total_seconds() // 60)
    return "|".join(
        [
            bucket_id,
            str(device_id or ""),
            cycle_start_local.date().isoformat(),
            cycle_start_local.isoformat(),
            str(target_minute),
        ]
    )


def _select_screenshot_event(
    events: Iterable[Event],
    target_at: datetime,
    selection_window_secs: int,
) -> Optional[Event]:
    best_event: Optional[Event] = None
    best_delta: Optional[float] = None
    for event in events:
        images = (event.data or {}).get("images") or []
        if not images:
            continue
        event_timestamp = event.timestamp.astimezone(timezone.utc)
        delta = abs((event_timestamp - target_at).total_seconds())
        if delta > selection_window_secs:
            continue
        if best_delta is None or delta < best_delta:
            best_event = event
            best_delta = delta
    return best_event


def _screenshot_attachment_id(image: Dict[str, Any], captured_at: str) -> str:
    return str(image.get("sha256") or image.get("path") or f"{captured_at}-{image.get('monitor_id', '')}")


def _is_idle_input_event(event: Dict[str, Any]) -> bool:
    data = event.get("data") or {}
    if not data:
        return True
    numeric_values: List[float] = []
    for key, value in data.items():
        if key == "bucket":
            continue
        if value in (None, False, ""):
            numeric_values.append(0.0)
            continue
        if isinstance(value, (int, float)):
            numeric_values.append(float(value))
            continue
        try:
            numeric_values.append(float(value))
        except (TypeError, ValueError):
            return False
    return bool(numeric_values) and all(value == 0.0 for value in numeric_values)


def _is_idle_afk_event(event: Dict[str, Any]) -> bool:
    data = event.get("data") or {}
    status = data.get("status") or data.get("state")
    if status is None:
        return False
    return str(status).strip().lower() in {"afk", "idle"}

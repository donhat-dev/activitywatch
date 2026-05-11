from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import sleep
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from aw_client import ActivityWatchClient
from aw_core.models import Event

from .config import AppConfig, resolve_state_path
from .odoo_client import OdooActivityTrackingClient, OdooPushConfig

logger = logging.getLogger(__name__)

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

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "buckets": {bucket_id: asdict(cursor) for bucket_id, cursor in self.buckets.items()},
            "attachments": sorted(self.attachments),
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

    def run_forever(self) -> None:
        logger.info("Starting aw-odoo-sync")
        self.client.wait_for_start()
        self.client.connect()
        self.odoo_client.start()
        try:
            while self.running:
                self.sync_once()
                sleep(self.config.server.poll_interval_secs)
        finally:
            self.client.disconnect()
            self.state.save()

    def sync_once(self) -> None:
        self.last_tracking_context = self.odoo_client.get_tracking_config()
        buckets = self.client.get_buckets()
        for bucket_id, bucket in buckets.items():
            bucket_type = self._resolve_bucket_type(bucket_id, bucket)
            if self._is_screenshot_bucket(bucket_id, bucket_type):
                self._sync_screenshot_bucket(bucket_id, bucket_type)
                continue
            if not self._should_sync_bucket_type(bucket_type):
                continue
            self._sync_bucket_events(bucket_id, bucket_type)
        self.state.save()

    def _sync_bucket_events(self, bucket_id: str, bucket_type: str) -> None:
        synced_events = 0
        skipped_events = 0
        while True:
            events = self._get_bucket_events(bucket_id)
            if not events:
                return
            payload_events = [self._serialize_event(bucket_id, event) for event in events]
            syncable_events = self.odoo_client.filter_syncable_events(payload_events)
            if not syncable_events:
                skipped_events += len(events)
                self._advance_cursor(bucket_id, events)
            else:
                result = self.odoo_client.push_bucket_events(
                    bucket_id,
                    bucket_type,
                    syncable_events,
                    tracking_context=self.last_tracking_context,
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

    def _sync_screenshot_bucket(self, bucket_id: str, bucket_type: str) -> None:
        if not self.config.screenshot.enabled:
            return
        uploaded_attachments = 0
        while True:
            events = self._get_bucket_events(bucket_id)
            if not events:
                return
            for event in events:
                images = (event.data or {}).get("images") or []
                captured_at = (event.data or {}).get("captured_at") or event.timestamp.astimezone(timezone.utc).isoformat()
                for image in images:
                    attachment_id = str(image.get("sha256") or image.get("path") or "")
                    if not attachment_id or self.state.has_attachment(attachment_id):
                        continue
                    result = self.odoo_client.push_screenshot_attachment(
                        bucket_id,
                        bucket_type,
                        captured_at,
                        image,
                        tracking_context=self.last_tracking_context,
                    )
                    if result is not None:
                        uploaded_attachments += 1
                        self.state.add_attachment(attachment_id)
            self._advance_cursor(bucket_id, events)
            if len(events) < self.config.server.batch_size:
                logger.info("Uploaded %s screenshot attachments from %s", uploaded_attachments, bucket_id)
                return

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
        event_id = event.id if event.id is not None else f"{bucket_id}-{int(event.timestamp.timestamp() * 1000)}"
        data = dict(event.data or {})
        data.setdefault("bucket", bucket_id)
        return {
            "id": str(event_id),
            "timestamp": event.timestamp.astimezone(timezone.utc).isoformat(),
            "duration": event.duration.total_seconds(),
            "data": data,
        }

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


def _bucket_matches(pattern: str, bucket_type: str) -> bool:
    if pattern.endswith("*"):
        return bucket_type.startswith(pattern[:-1])
    return pattern == bucket_type


def _parse_datetime(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    return datetime.fromisoformat(normalized)

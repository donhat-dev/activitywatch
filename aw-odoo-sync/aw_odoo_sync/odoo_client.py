from __future__ import annotations

import base64
import http.client
import json
import logging
import socket
import ssl
import urllib.error
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse
from uuid import uuid4

from .config import default_odoo_base_url, default_odoo_token

logger = logging.getLogger(__name__)


@dataclass
class OdooPushConfig:
    enabled: bool = False
    base_url: str = field(default_factory=default_odoo_base_url)
    pin_code: str = ""
    token: str = field(default_factory=default_odoo_token)
    employee_id: str = ""
    device_id: str = ""
    device_name: str = ""
    timeout_secs: float = 10.0
    push_screenshots: bool = True
    push_metadata_events: bool = False


class OdooActivityTrackingClient:
    def __init__(self, config: OdooPushConfig, agent_version: str = "0.1.0") -> None:
        self.config = config
        self.agent_version = agent_version
        default_base_url = default_odoo_base_url()
        self.base_url = (config.base_url or default_base_url).rstrip("/")
        self.hostname = socket.gethostname()
        self.device_id = config.device_id or self.hostname
        self._warned_disabled = False
        self._parsed_url = urlparse(self.base_url)
        self._conn: Optional[http.client.HTTPConnection] = None

    @property
    def enabled(self) -> bool:
        return bool(self.config.enabled)

    def start(self) -> None:
        if self.config.enabled and not (self.config.pin_code or self.config.employee_id) and not self._warned_disabled:
            logger.warning("Odoo push is enabled without pin_code or employee_id; Odoo will reject records without employee mapping")
            self._warned_disabled = True

    def stop(self) -> None:
        self._close_conn()

    def _get_conn(self) -> http.client.HTTPConnection:
        if self._conn is None:
            host = self._parsed_url.hostname or "localhost"
            port = self._parsed_url.port
            timeout = self.config.timeout_secs
            if self._parsed_url.scheme == "https":
                self._conn = http.client.HTTPSConnection(
                    host, port, timeout=timeout, context=ssl.create_default_context()
                )
            else:
                self._conn = http.client.HTTPConnection(host, port, timeout=timeout)
        return self._conn

    def _close_conn(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def get_tracking_config(self) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        self.start()
        response = self._post("/api/v1/activity_tracking/config", {"device": self._device_payload()})
        if not response or not isinstance(response, dict) or not response.get("success"):
            return None
        data = response.get("data")
        return data if isinstance(data, dict) else None

    def push_bucket_events(
        self,
        bucket_id: str,
        bucket_type: str,
        events: Iterable[Dict[str, Any]],
        tracking_context: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        filtered_events = self.filter_syncable_events(events)
        if not filtered_events:
            return None
        self.start()
        payload = {
            "device": self._device_payload(),
            "bucket": self._bucket_payload(bucket_id, bucket_type),
            "last_event_at": filtered_events[-1].get("timestamp") or _now_iso(),
            "events": filtered_events,
        }
        payload.update(_tracking_context_payload(tracking_context))
        return self._post("/api/v1/activity_tracking/bucket-events", payload)

    def push_screenshot_attachment(
        self,
        bucket_id: str,
        bucket_type: str,
        captured_at: str,
        image: Dict[str, Any],
        tracking_context: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        if not self.enabled or not self.config.push_screenshots:
            return None
        path_value = image.get("path")
        if not path_value:
            return None
        path = Path(path_value)
        if not path.exists():
            logger.warning("Cannot push screenshot to Odoo; file missing: %s", path)
            return None
        screenshot_id = image.get("sha256") or f"{captured_at}-{path.name}"
        with path.open("rb") as screenshot_file:
            image_data = base64.b64encode(screenshot_file.read()).decode("ascii")
        context_payload = _tracking_context_payload(tracking_context)
        payload = {
            "device": self._device_payload(),
            "bucket": self._bucket_payload(bucket_id, bucket_type),
            "attachment_id": screenshot_id,
            "captured_at": captured_at,
            "filename": path.name,
            "mimetype": "image/webp",
            "image_data": image_data,
            "metadata": {**image, "odoo_context": context_payload} if context_payload else image,
        }
        payload.update(context_payload)
        return self._post("/api/v1/activity_tracking/attachments", payload)

    def filter_syncable_events(self, events: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        filtered: List[Dict[str, Any]] = []
        for event in events:
            duration = event.get("duration") or 0
            try:
                duration_value = float(duration)
            except (TypeError, ValueError):
                logger.debug("Skipping event with invalid duration: %s", event)
                continue
            if duration_value <= 0:
                continue
            normalized = dict(event)
            normalized["duration"] = duration_value
            filtered.append(normalized)
        return filtered

    def _post(self, path: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        body = dict(payload)
        if self.config.pin_code:
            body["pin_code"] = self.config.pin_code
        if self.config.token:
            body["token"] = self.config.token
        if self.config.employee_id:
            body["employee_id"] = str(self.config.employee_id)
        body_bytes = json.dumps(body, default=str).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body_bytes)),
        }
        for attempt in range(2):
            try:
                conn = self._get_conn()
                conn.request("POST", path, body_bytes, headers)
                resp = conn.getresponse()
                data = resp.read().decode("utf-8")
                if resp.status >= 400:
                    logger.warning("Odoo push failed: HTTP %s %s", resp.status, data[:200])
                    return None
                return json.loads(data) if data else None
            except (http.client.RemoteDisconnected, ConnectionResetError, BrokenPipeError, OSError) as exc:
                logger.debug("Odoo connection lost (%s), reconnecting", exc)
                self._close_conn()
                if attempt == 0:
                    continue
                return None
            except Exception as exc:
                logger.warning("Odoo push failed: %s", exc)
                self._close_conn()
                return None
        return None

    def _device_payload(self) -> Dict[str, Any]:
        return {
            "id": self.device_id,
            "name": self.config.device_name or self.device_id,
            "hostname": self.hostname,
            "platform": _platform_name(),
            "agent_version": self.agent_version,
        }

    def _bucket_payload(self, bucket_id: str, bucket_type: str) -> Dict[str, Any]:
        return {
            "id": bucket_id,
            "name": bucket_id,
            "type": bucket_type,
            "client_name": self.agent_version.split("/", 1)[0],
            "hostname": self.hostname,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _tracking_context_payload(tracking_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not tracking_context:
        return {}
    payload: Dict[str, Any] = {}
    if "is_working" in tracking_context:
        payload["is_working"] = bool(tracking_context.get("is_working"))
    keys = (
        "timer_session_id",
        "account_analytic_line_id",
        "task_id",
        "task_name",
        "started_at",
    )
    payload.update({key: tracking_context[key] for key in keys if tracking_context.get(key) not in (None, "", False)})
    return payload


def _platform_name() -> str:
    import platform

    return platform.platform()

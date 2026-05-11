from __future__ import annotations

import base64
import hashlib
import hmac
import http.client
import json
import logging
import socket
import ssl
import time
import urllib.error
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse
from uuid import uuid4

logger = logging.getLogger(__name__)


@dataclass
class OdooPushConfig:
    enabled: bool = False
    base_url: str = "http://localhost:8069"
    pin_code: str = ""
    token: str = ""
    api_secret: str = ""
    sign_requests: bool = True
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
        self.base_url = (config.base_url or "http://localhost:8069").rstrip("/")
        self.hostname = socket.gethostname()
        self.device_id = config.device_id or self.hostname
        self._warned_disabled = False
        self._parsed_url = urlparse(self.base_url)
        self._conn: Optional[http.client.HTTPConnection] = None

    @property
    def enabled(self) -> bool:
        return bool(self.config.enabled)

    def start(self) -> None:
        if not self.enabled:
            return
        if not self.config.pin_code and not self.config.token and not self._warned_disabled:
            logger.info("Odoo pin_code/token not set; using public activity tracking endpoints")
            self._warned_disabled = True
        return

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

    def push_bucket_events(
        self,
        bucket_id: str,
        bucket_type: str,
        events: Iterable[Dict[str, Any]],
        tracking_context: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self.enabled or not self.config.push_metadata_events:
            return
        event_list = self._filter_duration_events(events)
        if not event_list:
            return
        self.start()
        payload = {
            "device": self._device_payload(),
            "bucket": self._bucket_payload(bucket_id, bucket_type),
            "last_event_at": event_list[-1].get("timestamp") or _now_iso(),
            "events": event_list,
        }
        payload.update(_tracking_context_payload(tracking_context))
        self._post("/api/v1/activity_tracking/bucket-events", payload)

    def push_screenshot_event(self, event_data: Dict[str, Any], tracking_context: Optional[Dict[str, Any]] = None) -> None:
        if not self.enabled:
            return
        self.start()
        context_payload = _tracking_context_payload(tracking_context)

        if self.config.push_metadata_events:
            captured_at = event_data.get("captured_at") or _now_iso()
            bucket_id = f"aw-watcher-screenshot-mini_{self.device_id}"
            metadata_event = dict(event_data)
            if context_payload:
                metadata_event["odoo_context"] = context_payload
            self.push_bucket_events(
                bucket_id,
                "os.desktop.screenshot",
                [
                    {
                        "id": f"screenshot-meta-{captured_at}",
                        "timestamp": captured_at,
                        "duration": 0,
                        "data": metadata_event,
                    }
                ],
                tracking_context=tracking_context,
            )

        if not self.config.push_screenshots:
            return

        for index, image in enumerate(event_data.get("images") or []):
            path_value = image.get("path")
            if not path_value:
                continue
            path = Path(path_value)
            if not path.exists():
                logger.warning("Cannot push screenshot to Odoo; file missing: %s", path)
                continue
            captured_at = event_data.get("captured_at") or _now_iso()
            screenshot_id = image.get("sha256") or f"{captured_at}-{index}"
            with path.open("rb") as screenshot_file:
                image_data = base64.b64encode(screenshot_file.read()).decode("ascii")
            payload = {
                "device": self._device_payload(),
                "bucket": self._bucket_payload(f"aw-watcher-screenshot-mini_{self.device_id}", "os.desktop.screenshot"),
                "attachment_id": screenshot_id,
                "captured_at": captured_at,
                "filename": path.name,
                "mimetype": "image/webp",
                "image_data": image_data,
                "metadata": {**image, "odoo_context": context_payload} if context_payload else image,
            }
            payload.update(context_payload)
            self._post("/api/v1/activity_tracking/attachments", payload)

    def get_tracking_config(self) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        self.start()
        response = self._post(
            "/api/v1/activity_tracking/config",
            {
                "device": self._device_payload(),
            },
        )
        if not response or not isinstance(response, dict):
            return None
        if not response.get("success"):
            return None
        data = response.get("data")
        return data if isinstance(data, dict) else None

    def _post(self, path: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        body = dict(payload)
        if self.config.pin_code:
            body["pin_code"] = self.config.pin_code
        body["token"] = self.config.token
        if self.config.employee_id:
            body["employee_id"] = self.config.employee_id
        if self.config.sign_requests and self.config.api_secret:
            timestamp = str(time.time())
            nonce = str(uuid4())
            payload_str = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
            signature_payload = f"{timestamp}|{nonce}|{payload_str}"
            signature = hmac.new(
                self.config.api_secret.encode("utf-8"),
                signature_payload.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            body.update(
                {
                    "_timestamp": timestamp,
                    "_nonce": nonce,
                    "_signature": signature,
                }
            )
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

    def _filter_duration_events(self, events: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        filtered_events: List[Dict[str, Any]] = []
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
            filtered_events.append(normalized)
        return filtered_events

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

from __future__ import annotations

import argparse
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from aw_core.config import load_config_toml

try:
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


DEFAULT_EVENT_TYPE = "os.desktop.screenshot"
DEFAULT_CLIENT_NAME = "aw-watcher-screenshot-mini"
DEFAULT_CONFIG_TOML = """
[trigger]
interval_secs = 300

[capture]
force_interval_secs = 60
dhash_threshold = 10

[cache]
cache_dir = "~/.local/share/activitywatch/screenshots-mini"
webp_quality = 75
max_width = 1920
max_height = 1080
webp_method = 6
cleanup_after_hours = 168
cleanup_every_n_captures = 20

[s3]
enabled = false
endpoint = ""
bucket = ""
access_key = ""
secret_key = ""
region = "auto"
key_prefix = ""

[aw_server]
host = "localhost"
port = 5600
pulse_time = 1200.0
bucket_id = "aw-watcher-screenshot-mini"
hostname = ""
timeout_secs = 1200
sync_enabled = true
event_type = "os.desktop.screenshot"
api_path = ""

[odoo]
enabled = false
base_url = "http://localhost:8069"
pin_code = ""
token = ""
api_secret = ""
sign_requests = true
employee_id = ""
device_id = ""
device_name = ""
timeout_secs = 10
push_screenshots = false
push_metadata_events = false

[logging]
enabled = true
dir = ""
level = "INFO"
to_stdout = true
to_file = true
rotate_when = "midnight"
rotate_interval = 1
backup_count = 14
filename = ""
""".strip()


@dataclass
class TriggerConfig:
    interval_secs: float = 300.0
    timeout_secs: Optional[float] = None


@dataclass
class CaptureConfig:
    force_interval_secs: float = 60.0
    dhash_threshold: int = 10


@dataclass
class CacheConfig:
    cache_dir: str = "~/.local/share/activitywatch/screenshots-mini"
    webp_quality: int = 75
    max_width: Optional[int] = None
    max_height: Optional[int] = None
    webp_method: int = 6
    cleanup_after_hours: Optional[int] = 168
    cleanup_every_n_captures: int = 20


@dataclass
class S3Config:
    enabled: bool = False
    endpoint: str = ""
    bucket: str = ""
    access_key: str = ""
    secret_key: str = ""
    region: str = "auto"
    key_prefix: str = ""


@dataclass
class AwServerConfig:
    host: Optional[str] = None
    port: Optional[int] = None
    pulse_time: Optional[float] = None
    bucket_id: str = DEFAULT_CLIENT_NAME
    hostname: str = socket.gethostname()
    timeout_secs: Optional[float] = 60.0
    sync_enabled: bool = True
    event_type: str = DEFAULT_EVENT_TYPE
    api_path: str = ""


@dataclass
class OdooConfig:
    enabled: bool = False
    base_url: str = "http://localhost:8069"
    pin_code: str = ""
    token: str = ""
    api_secret: str = ""
    sign_requests: bool = True
    employee_id: str = ""
    device_id: str = socket.gethostname()
    device_name: str = ""
    timeout_secs: float = 10.0
    push_screenshots: bool = False
    push_metadata_events: bool = False


@dataclass
class LoggingConfig:
    enabled: bool = True
    dir: str = ""
    level: str = "INFO"
    to_stdout: bool = True
    to_file: bool = True
    rotate_when: str = "midnight"
    rotate_interval: int = 1
    backup_count: int = 14
    filename: str = ""


@dataclass
class AppConfig:
    trigger: TriggerConfig
    capture: CaptureConfig
    cache: CacheConfig
    s3: S3Config
    aw_server: AwServerConfig
    odoo: OdooConfig
    logging: LoggingConfig
    config_path: Optional[str] = None
    testing: bool = False
    verbose: bool = False


def _load_toml(path: Path) -> Dict[str, Any]:
    with path.open("rb") as f:
        return tomllib.load(f)


def _merge(section: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(section)
    merged.update({k: v for k, v in overrides.items() if v is not None})
    return merged


def _as_dict(section: Any) -> Dict[str, Any]:
    if section is None:
        return {}
    return dict(section)


def _merge_raw(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for section in ("trigger", "capture", "cache", "s3", "aw_server", "odoo", "logging"):
        merged[section] = _merge(
            _as_dict(base.get(section)),
            _as_dict(overrides.get(section)),
        )
    return merged


def parse_args() -> AppConfig:
    parser = argparse.ArgumentParser(
        description="Capture screenshots periodically and enqueue ActivityWatch heartbeat events."
    )
    parser.add_argument("--config", default=None, help="Path to config.toml")
    parser.add_argument("--host", default=None, help="aw-server host")
    parser.add_argument("--port", type=int, default=None, help="aw-server port")
    parser.add_argument(
        "--testing",
        action="store_true",
        help="Use ActivityWatch testing mode (default test server port 5666)",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=None,
        help="Capture interval in seconds",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory where screenshots/WebP cache are stored",
    )
    parser.add_argument(
        "--verbose",
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    runtime_raw = load_config_toml(DEFAULT_CLIENT_NAME, DEFAULT_CONFIG_TOML)
    runtime_config_path = _runtime_config_path()

    if args.config:
        config_path = Path(args.config).expanduser()
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        override_raw = _load_toml(config_path)
        raw = _merge_raw(runtime_raw, override_raw)
    else:
        raw = runtime_raw
        config_path = runtime_config_path

    trigger = _merge(_as_dict(raw.get("trigger")), {"interval_secs": args.interval_seconds})
    capture = _as_dict(raw.get("capture"))
    cache = _merge(_as_dict(raw.get("cache")), {"cache_dir": args.output_dir})
    s3 = _as_dict(raw.get("s3"))
    aw_server = _merge(_as_dict(raw.get("aw_server")), {"host": args.host, "port": args.port})
    odoo = _as_dict(raw.get("odoo"))
    logging_cfg = _as_dict(raw.get("logging"))

    trigger_cfg = TriggerConfig(**trigger)
    capture_cfg = CaptureConfig(**capture)
    cache_cfg = CacheConfig(**cache)
    s3_cfg = S3Config(**s3)
    aw_cfg = AwServerConfig(**aw_server)
    odoo_cfg = OdooConfig(**odoo)
    log_cfg = LoggingConfig(**logging_cfg)

    if aw_cfg.pulse_time is None:
        aw_cfg.pulse_time = max(trigger_cfg.interval_secs * 4.0, 10.0)

    return AppConfig(
        trigger=trigger_cfg,
        capture=capture_cfg,
        cache=cache_cfg,
        s3=s3_cfg,
        aw_server=aw_cfg,
        odoo=odoo_cfg,
        logging=log_cfg,
        config_path=str(config_path),
        testing=args.testing,
        verbose=args.verbose,
    )


def _runtime_config_path() -> Path:
    from aw_core import dirs

    return Path(dirs.get_config_dir(DEFAULT_CLIENT_NAME)) / f"{DEFAULT_CLIENT_NAME}.toml"

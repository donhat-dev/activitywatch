from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

try:
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

from aw_core.dirs import get_config_dir, get_data_dir


@dataclass
class ServerConfig:
    host: str = "localhost"
    port: int = 5600
    bucket_allowlist: List[str] = field(default_factory=lambda: ["os.hid.input"])
    poll_interval_secs: float = 15.0
    lookback_secs: int = 300
    batch_size: int = 200
    state_file: str = ""


@dataclass
class OdooConfig:
    enabled: bool = False
    base_url: str = "http://localhost:8069"
    pin_code: str = ""
    employee_id: str = ""
    device_id: str = ""
    device_name: str = ""
    timeout_secs: float = 10.0
    push_screenshots: bool = True
    push_metadata_events: bool = False


@dataclass
class ScreenshotConfig:
    enabled: bool = True
    bucket_ids: List[str] = field(default_factory=lambda: ["aw-watcher-screenshot-mini"])


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
    server: ServerConfig
    odoo: OdooConfig
    screenshot: ScreenshotConfig
    logging: LoggingConfig
    config_path: Optional[str] = None
    verbose: bool = False


def parse_config(config_path: Optional[str] = None, verbose: bool = False) -> AppConfig:
    resolved_path: Optional[str] = None
    if config_path:
        resolved_path = str(Path(config_path).expanduser())
        raw = _load_toml(Path(resolved_path))
    else:
        raw, resolved_path = _load_default_toml()
    return AppConfig(
        server=ServerConfig(**raw.get("server", {})),
        odoo=OdooConfig(**raw.get("odoo", {})),
        screenshot=ScreenshotConfig(**raw.get("screenshot", {})),
        logging=LoggingConfig(**raw.get("logging", {})),
        config_path=resolved_path,
        verbose=verbose,
    )


def resolve_state_path(config: AppConfig) -> Path:
    configured = config.server.state_file.strip()
    if configured:
        return Path(configured).expanduser()
    return Path(get_data_dir("aw-odoo-sync")) / "state.json"


def _load_default_toml() -> tuple[Dict[str, Any], Optional[str]]:
    for path in _candidate_config_paths():
        if path.exists():
            return _load_toml(path), str(path)
    return {}, None


def _candidate_config_paths() -> List[Path]:
    candidates: List[Path] = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "config.toml")
    config_dir = Path(get_config_dir("aw-odoo-sync"))
    candidates.append(config_dir / "config.toml")
    return candidates


def _load_toml(path: Path) -> Dict[str, Any]:
    with path.open("rb") as config_file:
        return tomllib.load(config_file)

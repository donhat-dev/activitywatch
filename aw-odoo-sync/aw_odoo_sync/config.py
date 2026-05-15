from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

try:
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

from aw_core.dirs import get_config_dir, get_data_dir


DEFAULT_ODOO_BASE_URL = "http://localhost:8069"


def _clean_env_value(value: Optional[str]) -> str:
    return str(value).strip() if value is not None else ""


def _parse_env_content(content: str) -> Dict[str, str]:
    parsed: Dict[str, str] = {}
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if value and value[0] == value[-1] and value[0] in {"\"", "'"}:
            value = value[1:-1]
        parsed[key] = value
    return parsed


def _candidate_env_paths() -> List[Path]:
    candidates: List[Path] = []
    try:
        module_root = Path(__file__).resolve().parents[1]
        candidates.append(module_root / ".env")
    except Exception:
        pass
    cwd = Path.cwd()
    env_path = cwd / ".env"
    if env_path not in candidates:
        candidates.append(env_path)
    return candidates


@lru_cache(maxsize=1)
def _load_dotenv() -> Dict[str, str]:
    loaded: Dict[str, str] = {}
    for path in _candidate_env_paths():
        if not path.exists():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            continue
        loaded.update(_parse_env_content(content))
    return loaded


def _env_value(env: Dict[str, str], *keys: str) -> str:
    for key in keys:
        value = _clean_env_value(env.get(key) or os.getenv(key))
        if value:
            return value
    return ""


def _env_bool(default: bool, *keys: str) -> bool:
    value = _env_value(_load_dotenv(), *keys)
    if not value:
        return default
    return value.lower() not in {"0", "false", "no", "off"}


def default_odoo_base_url() -> str:
    env = _load_dotenv()
    return _env_value(env, "BASE_URL", "ODOO_URL", "ODOO_BASE_URL") or DEFAULT_ODOO_BASE_URL


def default_odoo_token() -> str:
    env = _load_dotenv()
    return _env_value(env, "TOKEN", "ODOO_TOKEN")


def default_odoo_verify_ssl() -> bool:
    return _env_bool(True, "ODOO_VERIFY_SSL", "VERIFY_SSL")


@dataclass
class ServerConfig:
    host: str = "localhost"
    port: int = 5600
    bucket_allowlist: List[str] = field(default_factory=lambda: ["os.hid.input"])
    poll_interval_secs: float = 10.0
    lookback_secs: int = 300
    batch_size: int = 200
    state_file: str = ""


@dataclass
class OdooConfig:
    enabled: bool = False
    base_url: str = field(default_factory=default_odoo_base_url)
    pin_code: str = ""
    token: str = field(default_factory=default_odoo_token)
    employee_id: str = ""
    device_id: str = ""
    device_name: str = ""
    timeout_secs: float = 10.0
    verify_ssl: bool = field(default_factory=default_odoo_verify_ssl)
    push_screenshots: bool = True
    push_metadata_events: bool = False


@dataclass
class ScreenshotConfig:
    enabled: bool = True
    bucket_ids: List[str] = field(default_factory=lambda: ["aw-watcher-screenshot-mini"])
    selection_window_secs: int = 120


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
    odoo_raw = dict(raw.get("odoo", {}))
    if not odoo_raw.get("base_url"):
        odoo_raw["base_url"] = default_odoo_base_url()
    if not odoo_raw.get("token"):
        odoo_raw["token"] = default_odoo_token()
    return AppConfig(
        server=ServerConfig(**raw.get("server", {})),
        odoo=OdooConfig(**odoo_raw),
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

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Optional

from aw_core.dirs import get_log_dir

from aw_odoo_sync.config import LoggingConfig, parse_config, resolve_state_path
from aw_odoo_sync.sync import ActivityWatchOdooSyncService

logger = logging.getLogger(__name__)


def _default_log_dir() -> Path:
    env_log_dir = os.getenv("AW_LOG_DIR")
    if env_log_dir:
        return Path(env_log_dir).expanduser()
    env_log_root = os.getenv("AW_LOG_ROOT")
    if env_log_root:
        return Path(env_log_root).expanduser() / "aw-odoo-sync"
    if getattr(sys, "frozen", False):
        return Path(get_log_dir("aw-odoo-sync"))
    return Path(get_log_dir("aw-odoo-sync"))


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
    return f"aw-odoo-sync_{now_str}.log"


def _mask_secret(value: str, visible: int = 4) -> str:
    if not value:
        return ""
    if visible <= 0:
        return "*" * len(value)
    if len(value) <= visible:
        return "*" * len(value)
    return "*" * (len(value) - visible) + value[-visible:]


def _log_startup_config(config, log_path: Optional[Path]) -> None:
    logger.info("Sync config path: %s", config.config_path or "<auto>")
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
        "Server: host=%s port=%s poll_interval_secs=%s lookback_secs=%s batch_size=%s state_file=%s bucket_allowlist=%s",
        config.server.host,
        config.server.port,
        config.server.poll_interval_secs,
        config.server.lookback_secs,
        config.server.batch_size,
        config.server.state_file or "",
        config.server.bucket_allowlist,
    )
    logger.info("State path: %s", resolve_state_path(config))
    logger.info(
        "Screenshot: enabled=%s bucket_ids=%s selection_window_secs=%s",
        config.screenshot.enabled,
        config.screenshot.bucket_ids,
        config.screenshot.selection_window_secs,
    )
    logger.info(
        "Odoo: enabled=%s base_url=%s pin_code=%s employee_id=%s device_id=%s device_name=%s timeout_secs=%s verify_ssl=%s push_screenshots=%s push_metadata_events=%s",
        config.odoo.enabled,
        config.odoo.base_url,
        _mask_secret(config.odoo.pin_code),
        config.odoo.employee_id,
        config.odoo.device_id,
        config.odoo.device_name,
        config.odoo.timeout_secs,
        config.odoo.verify_ssl,
        config.odoo.push_screenshots,
        config.odoo.push_metadata_events,
    )


def _configure_logging(verbose: bool, config: LoggingConfig) -> Optional[Path]:
    if not config.enabled:
        return None
    level = _resolve_log_level(verbose, config.level)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Central Odoo sync daemon for ActivityWatch")
    parser.add_argument("--config", default=None, help="Path to config.toml")
    parser.add_argument("--once", action="store_true", help="Run one sync cycle and exit")
    parser.add_argument("--verbose", "--debug", action="store_true", help="Enable verbose logging")
    args = parser.parse_args()

    config = parse_config(args.config, verbose=args.verbose)
    log_path = _configure_logging(args.verbose, config.logging)
    if log_path:
        logger.info("Logging initialized at %s", log_path)
    _log_startup_config(config, log_path)
    service = ActivityWatchOdooSyncService(config)
    if args.once:
        service.client.wait_for_start()
        service.client.connect()
        try:
            service.sync_once()
        finally:
            service.client.disconnect()
            service.state.save()
        return
    service.run_forever()


if __name__ == "__main__":
    main()

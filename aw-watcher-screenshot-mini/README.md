# aw-watcher-screenshot-mini

Portable screenshot watcher for ActivityWatch with smart filtering, WebP cache, and optional S3 upload.

## Features
- Periodic screenshot capture
- Config file support via `config.toml`
- Perceptual hash filtering for unchanged screenshots
- Force-capture interval to avoid over-filtering
- WebP cache/compression
- Optional S3-compatible upload
- Metadata heartbeat events queued to ActivityWatch
- Disk-backed offline queue via `aw-client`
- Portable packaging via PyInstaller

## Usage

```bash
poetry install
poetry run aw-watcher-screenshot-mini --config config.toml
```

Or with CLI overrides:

```bash
poetry run aw-watcher-screenshot-mini --interval-seconds 5 --output-dir ./cache
```

## Configuration

By default the watcher creates and reads its runtime config at the standard ActivityWatch config location:

- Windows: `%LocalAppData%\activitywatch\activitywatch\aw-watcher-screenshot-mini\aw-watcher-screenshot-mini.toml`
- Linux/macOS: the platform-specific ActivityWatch config directory for `aw-watcher-screenshot-mini`

The generated file contains commented defaults. Uncomment the keys you want to override. For example, lower `trigger.interval_secs` to `60` for testing:

```toml
[trigger]
interval_secs = 60

[capture]
force_interval_secs = 60
```

You can also pass an explicit config file:

```bash
poetry run aw-watcher-screenshot-mini --config config.toml
```

Example full config:

```toml
[trigger]
interval_secs = 60

[capture]
force_interval_secs = 60
dhash_threshold = 10

[cache]
cache_dir = "cache"
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
pulse_time = 60.0
bucket_id = "aw-watcher-screenshot-mini"
hostname = ""
timeout_secs = 60
sync_enabled = true
event_type = "os.desktop.screenshot"
api_path = ""
```

## Package

```bash
make package
```

Output will be created in `dist/aw-watcher-screenshot-mini/`.

## Notes
- On Linux it needs a GUI session and one of: `gnome-screenshot`, `grim`, `scrot`, `import`.
- On Windows it uses `pywin32` screen capture APIs.
- Event payload stores screenshot file metadata and optional S3 object references, not raw image bytes.
- Odoo upload policy is owned by `aw-odoo-sync`; this watcher captures local ActivityWatch events only.
- Cache files are stored in hourly folders for easier sync and cleanup.
- Compression can be tuned using `webp_quality`, `webp_method`, `max_width`, and `max_height`.
- Cache cleanup can be tuned with `cleanup_after_hours` and `cleanup_every_n_captures`.
- HTTP sync can be disabled or redirected using `aw_server.sync_enabled`, `event_type`, and `api_path`.
- Runtime logs are written to `aw-watcher-screenshot-mini.log` next to the bundled executable, or into the configured cache directory when running from source.
- On Windows, screen lock/unlock and remote-session transitions can temporarily break desktop capture. The watcher now retries briefly, logs a warning, and resumes automatically when the desktop becomes available again.

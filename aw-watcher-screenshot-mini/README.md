# aw-watcher-screenshot-mini

Portable screenshot watcher PoC for ActivityWatch.

## Features
- Periodic screenshot capture
- Metadata heartbeat events queued to ActivityWatch
- Disk-backed offline queue via `aw-client`
- Portable packaging via PyInstaller

## Usage

```bash
poetry install
poetry run aw-watcher-screenshot-mini --interval-minutes 5
```

## Package

```bash
make package
```

Output will be created in `dist/aw-watcher-screenshot-mini/`.

## Notes
- On Linux it needs a GUI session and one of: `gnome-screenshot`, `grim`, `scrot`, `import`.
- On Windows it uses `pywin32` screen capture APIs.
- Event payload stores screenshot file metadata, not raw image bytes.

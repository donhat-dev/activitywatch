from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class ScreenshotCaptureError(RuntimeError):
    pass


def capture_screenshot(output_path: Path) -> str:
    if os.name == "nt":
        return _capture_windows(output_path)
    return _capture_unix(output_path)


def _capture_unix(output_path: Path) -> str:
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        raise ScreenshotCaptureError(
            "No DISPLAY/WAYLAND_DISPLAY found; screenshot capture requires a GUI session"
        )

    backends = [
        ("gnome-screenshot", ["gnome-screenshot", "-f", str(output_path)]),
        ("grim", ["grim", str(output_path)]),
        ("scrot", ["scrot", str(output_path)]),
        ("import", ["import", "-window", "root", str(output_path)]),
    ]

    last_error: Optional[Exception] = None
    for name, command in backends:
        if shutil.which(command[0]) is None:
            continue
        try:
            subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            if output_path.exists() and output_path.stat().st_size > 0:
                return name
        except Exception as exc:
            last_error = exc
            logger.warning("Screenshot backend '%s' failed: %s", name, exc)

    raise ScreenshotCaptureError(
        "No working screenshot backend found"
        + (f": {last_error}" if last_error else "")
    )


def _capture_windows(output_path: Path) -> str:
    try:
        import win32gui
        import win32ui
        from win32con import SRCCOPY
        from win32api import GetSystemMetrics
    except ImportError as exc:
        raise ScreenshotCaptureError(f"Windows screenshot dependencies unavailable: {exc}")

    left = 0
    top = 0
    width = GetSystemMetrics(0)
    height = GetSystemMetrics(1)

    hwnd = win32gui.GetDesktopWindow()
    hwnd_dc = win32gui.GetWindowDC(hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
    save_dc.SelectObject(bitmap)
    save_dc.BitBlt((0, 0), (width, height), mfc_dc, (left, top), SRCCOPY)

    bitmap.SaveBitmapFile(save_dc, str(output_path))

    win32gui.DeleteObject(bitmap.GetHandle())
    save_dc.DeleteDC()
    mfc_dc.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwnd_dc)

    return "win32gui"

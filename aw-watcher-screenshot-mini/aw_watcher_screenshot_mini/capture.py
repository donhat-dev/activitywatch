from __future__ import annotations

import ctypes
import logging
import os
import shutil
import subprocess
from pathlib import Path
from time import sleep
from typing import Dict, Optional, Tuple

from PIL import Image

logger = logging.getLogger(__name__)

WINDOWS_CAPTURE_RETRY_DELAYS = (0.25, 1.0)


class ScreenshotCaptureError(RuntimeError):
    pass


class ScreenshotTransientError(ScreenshotCaptureError):
    pass


def capture_screenshot(output_path: Path) -> str:
    if os.name == "nt":
        return _capture_windows(output_path)
    return _capture_unix(output_path)


def capture_screenshots(output_dir: Path, timestamp: str) -> Tuple[str, Dict[str, Path]]:
    if os.name == "nt":
        return _capture_windows_all(output_dir, timestamp)

    single = output_dir / f"screenshot-{timestamp}.bmp"
    backend = _capture_unix(single)
    return backend, {"display-0": single}


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

    hwnd = None
    hwnd_dc = None
    mfc_dc = None
    save_dc = None
    bitmap = None
    try:
        hwnd = win32gui.GetDesktopWindow()
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
        save_dc.SelectObject(bitmap)
        save_dc.BitBlt((0, 0), (width, height), mfc_dc, (left, top), SRCCOPY)
        bitmap.SaveBitmapFile(save_dc, str(output_path))
    except Exception as exc:
        raise ScreenshotTransientError(_describe_windows_capture_failure(exc)) from exc
    finally:
        if bitmap is not None:
            try:
                win32gui.DeleteObject(bitmap.GetHandle())
            except Exception:
                pass
        if save_dc is not None:
            try:
                save_dc.DeleteDC()
            except Exception:
                pass
        if mfc_dc is not None:
            try:
                mfc_dc.DeleteDC()
            except Exception:
                pass
        if hwnd is not None and hwnd_dc is not None:
            try:
                win32gui.ReleaseDC(hwnd, hwnd_dc)
            except Exception:
                pass

    return "win32gui"


def _capture_windows_all(output_dir: Path, timestamp: str) -> Tuple[str, Dict[str, Path]]:
    try:
        from PIL import ImageGrab
    except ImportError as exc:
        raise ScreenshotCaptureError(f"Windows multi-monitor dependencies unavailable: {exc}")

    if hasattr(ImageGrab, "grab"):
        for attempt, delay in enumerate((0.0, *WINDOWS_CAPTURE_RETRY_DELAYS), start=1):
            try:
                displays = getattr(ImageGrab, "grab")(all_screens=True)
                if displays is not None:
                    output_path = output_dir / f"screenshot-{timestamp}-display-0.bmp"
                    displays.save(output_path)
                    return "ImageGrab", {"display-0": output_path}
            except Exception as exc:
                if attempt <= len(WINDOWS_CAPTURE_RETRY_DELAYS):
                    logger.warning(
                        "ImageGrab all_screens capture failed (attempt %s/%s): %s",
                        attempt,
                        len(WINDOWS_CAPTURE_RETRY_DELAYS) + 1,
                        _describe_windows_capture_failure(exc),
                    )
                    sleep(delay)
                else:
                    logger.warning(
                        "ImageGrab all_screens capture failed: %s",
                        _describe_windows_capture_failure(exc),
                    )

    fallback = output_dir / f"screenshot-{timestamp}.bmp"
    last_exc: Optional[Exception] = None
    for attempt, delay in enumerate((0.0, *WINDOWS_CAPTURE_RETRY_DELAYS), start=1):
        try:
            backend = _capture_windows(fallback)
            return backend, {"display-0": fallback}
        except ScreenshotTransientError as exc:
            last_exc = exc
            if attempt <= len(WINDOWS_CAPTURE_RETRY_DELAYS):
                logger.warning(
                    "BitBlt fallback capture failed (attempt %s/%s): %s",
                    attempt,
                    len(WINDOWS_CAPTURE_RETRY_DELAYS) + 1,
                    exc,
                )
                sleep(delay)
            else:
                break

    raise ScreenshotTransientError(
        "Windows desktop capture temporarily unavailable; likely during screen lock/unlock or remote session transition"
    ) from last_exc


def _describe_windows_capture_failure(exc: Exception) -> str:
    detail = str(exc).strip() or exc.__class__.__name__
    if _input_desktop_available():
        return detail
    return f"{detail} (input desktop unavailable)"


def _input_desktop_available() -> bool:
    if os.name != "nt":
        return True

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    open_input_desktop = user32.OpenInputDesktop
    open_input_desktop.argtypes = [ctypes.c_uint, ctypes.c_bool, ctypes.c_uint]
    open_input_desktop.restype = ctypes.c_void_p

    close_desktop = user32.CloseDesktop
    close_desktop.argtypes = [ctypes.c_void_p]
    close_desktop.restype = ctypes.c_bool

    desktop = open_input_desktop(0, False, 0x0100)
    if not desktop:
        return False

    close_desktop(desktop)
    return True


def load_image(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGB")

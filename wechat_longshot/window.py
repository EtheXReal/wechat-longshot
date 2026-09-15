"""Find and capture the WeChat window.

Capture goes through ScreenCaptureKit (macOS 14+). The older
``CGWindowListCreateImage`` API returns ``None`` for other apps' windows on recent
macOS releases, so it is not used. Screen Recording permission is required.
"""

from __future__ import annotations

import threading
import time

import numpy as np
import Quartz

from .errors import CaptureFailed, WindowNotFound
from .types import Frame, WindowInfo

_OWNER_NAMES = {"WeChat", "Weixin", "微信"}
_CAPTURE_TIMEOUT_S = 5.0


def _window_infos() -> list[dict]:
    wl = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionAll, Quartz.kCGNullWindowID)
    return [dict(w) for w in wl] if wl else []


def _pick_main_window(infos: list[dict]) -> dict:
    best = None
    for w in infos:
        if w.get("kCGWindowOwnerName") not in _OWNER_NAMES or w.get("kCGWindowLayer") != 0:
            continue
        b = w.get("kCGWindowBounds") or {}
        if b.get("Width", 0) < 600 or b.get("Height", 0) < 400:
            continue
        area = b["Width"] * b["Height"]
        if best is None or area > best[0]:
            best = (area, w)
    if best is None:
        raise WindowNotFound(
            "No WeChat main window found. Is WeChat running with a chat window open "
            "(not minimised to the Dock)?"
        )
    return best[1]


class _Capturer:
    """Holds the ScreenCaptureKit filter/config for one window."""

    def __init__(self, window_id: int, width_pt: float, height_pt: float, scale: float) -> None:
        import ScreenCaptureKit as SCK

        self._sck = SCK
        content = self._shareable_content()
        matches = [w for w in content.windows() if int(w.windowID()) == window_id]
        if not matches:
            raise WindowNotFound(f"Window {window_id} is not capturable via ScreenCaptureKit.")
        self._filter = SCK.SCContentFilter.alloc().initWithDesktopIndependentWindow_(matches[0])
        cfg = SCK.SCStreamConfiguration.alloc().init()
        cfg.setWidth_(int(round(width_pt * scale)))
        cfg.setHeight_(int(round(height_pt * scale)))
        cfg.setShowsCursor_(False)
        self._cfg = cfg

    def _shareable_content(self):
        done = threading.Event()
        box: dict = {}

        def cb(content, err):
            box["content"], box["err"] = content, err
            done.set()

        self._sck.SCShareableContent.getShareableContentExcludingDesktopWindows_onScreenWindowsOnly_completionHandler_(  # noqa: E501
            False, False, cb
        )
        if (
            not done.wait(_CAPTURE_TIMEOUT_S)
            or box.get("err") is not None
            or box.get("content") is None
        ):
            raise CaptureFailed(
                "ScreenCaptureKit refused to list windows. Grant Screen Recording permission to "
                "your terminal in System Settings > Privacy & Security > Screen Recording, "
                f"then restart it. ({box.get('err')})"
            )
        return box["content"]

    def capture(self, retries: int = 3) -> Frame:
        last: Exception | None = None
        for _ in range(retries):
            try:
                return self._capture_once()
            except CaptureFailed as e:  # transient while the window is animating / re-created
                last = e
                time.sleep(0.15)
        raise last  # type: ignore[misc]

    def _capture_once(self) -> Frame:
        done = threading.Event()
        box: dict = {}

        def cb(img, err):
            box["img"], box["err"] = img, err
            done.set()

        self._sck.SCScreenshotManager.captureImageWithFilter_configuration_completionHandler_(
            self._filter, self._cfg, cb
        )
        if not done.wait(_CAPTURE_TIMEOUT_S) or box.get("img") is None:
            raise CaptureFailed(f"Window capture failed: {box.get('err')}")
        return _cgimage_to_bgr(box["img"])


def _cgimage_to_bgr(img) -> Frame:
    w = Quartz.CGImageGetWidth(img)
    h = Quartz.CGImageGetHeight(img)
    bpr = Quartz.CGImageGetBytesPerRow(img)
    data = Quartz.CGDataProviderCopyData(Quartz.CGImageGetDataProvider(img))
    if data is None or w == 0 or h == 0:
        raise CaptureFailed("Captured image is empty (no Screen Recording permission?).")
    buf = np.frombuffer(data, dtype=np.uint8)[: bpr * h].reshape(h, bpr // 4, 4)[:, :w, :]
    info = Quartz.CGImageGetBitmapInfo(img)
    little = (info & Quartz.kCGBitmapByteOrderMask) == Quartz.kCGBitmapByteOrder32Little
    # 32Little + AlphaPremultipliedFirst  => bytes are B,G,R,A (what OpenCV wants).
    # Big-endian ARGB                      => bytes are A,R,G,B.
    bgr = buf[:, :, :3] if little else buf[:, :, 3:0:-1]
    return np.ascontiguousarray(bgr)


_capturers: dict[int, _Capturer] = {}


def find_wechat_window() -> WindowInfo:
    w = _pick_main_window(_window_infos())
    b = w["kCGWindowBounds"]
    wid = int(w["kCGWindowNumber"])
    scale = _display_scale(b["X"] + b["Width"] / 2, b["Y"] + b["Height"] / 2)
    return WindowInfo(
        window_id=wid,
        pid=int(w["kCGWindowOwnerPID"]),
        title=str(w.get("kCGWindowName") or "WeChat"),
        x=float(b["X"]),
        y=float(b["Y"]),
        width=float(b["Width"]),
        height=float(b["Height"]),
        scale=scale,
    )


def _display_scale(x: float, y: float) -> float:
    """Backing scale factor of the display containing screen point (x, y)."""
    err, ids, count = Quartz.CGGetDisplaysWithPoint(Quartz.CGPointMake(x, y), 4, None, None)
    if err == 0 and count:
        did = ids[0]
        mode = Quartz.CGDisplayCopyDisplayMode(did)
        if mode is not None:
            px = Quartz.CGDisplayModeGetPixelWidth(mode)
            pt = Quartz.CGDisplayModeGetWidth(mode)
            if pt:
                return round(px / pt, 1)
    return 2.0


def capture_window(win: WindowInfo) -> Frame:
    cap = _capturers.get(win.window_id)
    if cap is None:
        cap = _Capturer(win.window_id, win.width, win.height, win.scale)
        _capturers[win.window_id] = cap
    return cap.capture()


def activate_window(win: WindowInfo) -> None:
    """Un-minimise (if needed), raise and focus the WeChat window."""
    import AppKit
    import ApplicationServices as AS

    app_el = AS.AXUIElementCreateApplication(win.pid)
    err, ax_wins = AS.AXUIElementCopyAttributeValue(app_el, "AXWindows", None)
    if err == 0 and ax_wins:
        for w in ax_wins:
            _, minimised = AS.AXUIElementCopyAttributeValue(w, "AXMinimized", None)
            if minimised:
                AS.AXUIElementSetAttributeValue(w, "AXMinimized", False)
                time.sleep(0.4)
            AS.AXUIElementPerformAction(w, "AXRaise")
    app = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(win.pid)
    deadline = time.monotonic() + 3.0
    while True:
        if app is not None:
            app.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)
        time.sleep(0.25)
        if is_window_frontmost(win) or time.monotonic() > deadline:
            break
    time.sleep(0.3)


def is_window_frontmost(win: WindowInfo) -> bool:
    """True when the WeChat window is on screen and nothing covers its centre."""
    cx, cy = win.x + win.width / 2, win.y + win.height / 2
    wl = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID
    )
    for w in wl or []:
        if w.get("kCGWindowLayer") != 0:
            continue
        b = w.get("kCGWindowBounds") or {}
        if b.get("X", 0) <= cx <= b.get("X", 0) + b.get("Width", 0) and b.get(
            "Y", 0
        ) <= cy <= b.get("Y", 0) + b.get("Height", 0):
            return int(w.get("kCGWindowNumber", -1)) == win.window_id
    return False


def minimize_window(win: WindowInfo) -> None:
    """Send the WeChat window back to the Dock (used to restore the user's layout)."""
    import ApplicationServices as AS

    app_el = AS.AXUIElementCreateApplication(win.pid)
    err, ax_wins = AS.AXUIElementCopyAttributeValue(app_el, "AXWindows", None)
    if err == 0 and ax_wins:
        for w in ax_wins:
            AS.AXUIElementSetAttributeValue(w, "AXMinimized", True)

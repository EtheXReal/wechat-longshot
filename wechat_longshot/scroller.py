"""Scroll the WeChat message list with synthetic scroll-wheel events and wait for it to settle."""

from __future__ import annotations

import time

import numpy as np
import Quartz

from .types import CaptureFn, Frame, Rect, WindowInfo

# WeChat ignores single huge deltas (it treats them like a jump and clamps), so we
# emit a trackpad-like burst of small events instead.
_MAX_EVENT_DELTA_PT = 40
_EVENT_GAP_S = 0.004


class Scroller:
    """Posts scroll events into the message list and returns settled frames.

    ``region`` may be ``None`` until the message area has been detected; a geometric
    guess (right 60 % of the window, vertical centre) is used for the pointer then.
    """

    def __init__(
        self,
        win: WindowInfo,
        region: Rect | None,
        capture: CaptureFn,
        settle_timeout: float = 2.5,
        settle_interval: float = 0.06,
        pre_settle_delay: float = 0.12,
        gain: float = 1.0,
    ) -> None:
        self.win = win
        # WeChat scrolls its list by more than the wheel delta we send (1.5x on this
        # build). ``gain`` = actual_px / requested_px; see ``pipeline.calibrate_scroll``.
        self.gain = gain
        self.region = region
        self.capture = capture
        self.settle_timeout = settle_timeout
        self.settle_interval = settle_interval
        self.pre_settle_delay = pre_settle_delay
        self.last_frame: Frame | None = None

    # -- geometry -----------------------------------------------------------------

    def _pointer_px(self) -> tuple[int, int]:
        if self.region is not None:
            return self.region.center
        w = int(self.win.width * self.win.scale)
        h = int(self.win.height * self.win.scale)
        return (int(w * 0.7), int(h * 0.5))

    def _compare_rect(self) -> Rect | None:
        return self.region

    # -- events ---------------------------------------------------------------------

    def _move_pointer(self) -> None:
        px, py = self._pointer_px()
        sx, sy = self.win.to_screen_point(px, py)
        ev = Quartz.CGEventCreateMouseEvent(
            None, Quartz.kCGEventMouseMoved, Quartz.CGPointMake(sx, sy), Quartz.kCGMouseButtonLeft
        )
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)

    def _post_wheel(self, dy_pt: float) -> None:
        """Positive dy_pt scrolls the view towards newer content (content moves up)."""
        remaining = dy_pt
        sign = 1 if dy_pt > 0 else -1
        while abs(remaining) > 0.5:
            step = sign * min(abs(remaining), _MAX_EVENT_DELTA_PT)
            # Quartz wheel axis 1: positive = scroll up (content moves down). Invert.
            ev = Quartz.CGEventCreateScrollWheelEvent(
                None, Quartz.kCGScrollEventUnitPixel, 1, int(round(-step))
            )
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
            remaining -= step
            time.sleep(_EVENT_GAP_S)

    # -- public API -----------------------------------------------------------------

    def current(self) -> Frame:
        self.last_frame = self.capture()
        return self.last_frame

    def settle(self) -> Frame:
        """Capture until two consecutive frames are identical inside the region."""
        rect = self._compare_rect()
        deadline = time.monotonic() + self.settle_timeout
        prev = self.capture()
        while True:
            time.sleep(self.settle_interval)
            cur = self.capture()
            a = rect.crop(prev) if rect else prev
            b = rect.crop(cur) if rect else cur
            if a.shape == b.shape and np.array_equal(a, b):
                self.last_frame = cur
                return cur
            if time.monotonic() > deadline:
                self.last_frame = cur
                return cur
            prev = cur

    def scroll(self, dy_px: int) -> Frame:
        """Scroll by ``dy_px`` image pixels (positive = newer) and return the settled frame."""
        self._move_pointer()
        time.sleep(0.02)
        self._post_wheel(dy_px / self.gain / self.win.scale)
        time.sleep(self.pre_settle_delay)
        return self.settle()

    def page_down(self, fraction: float = 0.6) -> Frame:
        return self.scroll(int(self._page_px() * fraction))

    def page_up(self, fraction: float = 0.6) -> Frame:
        return self.scroll(-int(self._page_px() * fraction))

    def _page_px(self) -> int:
        if self.region is not None:
            return self.region.h
        return int(self.win.height * self.win.scale * 0.6)

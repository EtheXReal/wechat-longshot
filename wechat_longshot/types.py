"""Shared data types.

Coordinate conventions
----------------------
* ``Frame``: a captured image of the WeChat window as a numpy ``uint8`` array in
  **BGR** order (OpenCV convention), shape ``(H, W, 3)``. On Retina displays the
  image is ``scale`` (usually 2.0) times larger than the window's size in points.
* ``Rect``: always in **image pixels** of a ``Frame`` (origin top-left), never in
  screen points. Convert to screen points with ``WindowInfo.to_screen_point``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import numpy as np

Frame = np.ndarray  # (H, W, 3) uint8 BGR


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def x2(self) -> int:
        return self.x + self.w

    @property
    def y2(self) -> int:
        return self.y + self.h

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.w // 2, self.y + self.h // 2)

    def crop(self, frame: Frame) -> Frame:
        return frame[self.y : self.y2, self.x : self.x2]


@dataclass(frozen=True)
class WindowInfo:
    """A WeChat window as reported by Quartz."""

    window_id: int
    pid: int
    title: str
    # bounds in screen points (top-left origin, as CGWindowListCopyWindowInfo reports)
    x: float
    y: float
    width: float
    height: float
    scale: float  # image pixels per screen point (2.0 on Retina)

    def to_screen_point(self, px: int, py: int) -> tuple[float, float]:
        """Convert an image-pixel coordinate in this window's Frame to a global screen point."""
        return (self.x + px / self.scale, self.y + py / self.scale)


@dataclass(frozen=True)
class TextBox:
    """One OCR result, in image pixels of the frame it was recognised from."""

    text: str
    rect: Rect
    confidence: float


@dataclass(frozen=True)
class TimeLabel:
    """A WeChat time separator ("Friday 14:38", "昨天 10:06", "9/3 22:13" ...) found by OCR."""

    when: datetime
    box: TextBox


CaptureFn = Callable[[], Frame]
ScrollFn = Callable[
    [int], Frame
]  # scroll by N image pixels (positive = view newer); returns the settled frame

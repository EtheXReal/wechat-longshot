"""Stitch successive frames of a scrolling list into one tall image.

For each new frame we pick a distinctive horizontal strip from the previous frame
(the window with the highest pixel variance inside its lower part), locate it in
the new frame with normalised cross-correlation, and append only the rows below
the overlap. Working with full-width strips reduces the 2-D search to a 1-D one and
makes repeated content (identical stickers, blank gaps) much less ambiguous.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .errors import StitchFailed
from .types import Frame, Rect


@dataclass
class StitchResult:
    shift: int  # rows of new content appended (0 => frame identical / no progress)
    confidence: float
    strip_y: int  # where the probe strip was taken from in the previous frame


def measure_shift(prev: Frame, cur: Frame, region: Rect, strip_h: int = 160) -> tuple[int, float]:
    """How many rows did the list move between two full frames? (positive = towards newer)

    Uses a textured strip from the *middle* of ``prev`` so shifts of up to ~1/3 of the
    region height in either direction can be measured. Returns (shift, confidence).
    """
    pg = cv2.cvtColor(region.crop(prev), cv2.COLOR_BGR2GRAY)
    cg = cv2.cvtColor(region.crop(cur), cv2.COLOR_BGR2GRAY)
    h = pg.shape[0]
    row_var = pg.astype(np.float32).var(axis=1)
    win = np.convolve(row_var, np.ones(strip_h, dtype=np.float32) / strip_h, mode="valid")
    win[: int(h * 0.35)] = -1
    win[int(h * 0.65) :] = -1
    sy = int(np.argmax(win))
    res = cv2.matchTemplate(cg, pg[sy : sy + strip_h], cv2.TM_CCOEFF_NORMED)[:, 0]
    y = int(np.argmax(res))
    return sy - y, float(res[y])


class Stitcher:
    def __init__(
        self,
        region: Rect,
        min_confidence: float = 0.95,
        strip_h: int | None = None,
        search_slack: int = 60,
    ) -> None:
        self.region = region
        self.min_confidence = min_confidence
        self.strip_h = strip_h or max(24, region.h // 12)
        self.search_slack = search_slack
        self._chunks: list[Frame] = []
        self._prev: Frame | None = None
        self.history: list[StitchResult] = []

    # -- helpers --------------------------------------------------------------------

    @staticmethod
    def _gray(img: Frame) -> np.ndarray:
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    def _pick_strip(self, gray: np.ndarray, expected_shift: int | None) -> int:
        """Return the y of the most textured ``strip_h`` window that will still be visible
        after scrolling by ``expected_shift`` (i.e. from the lower part of ``gray``)."""
        h = gray.shape[0]
        lo = int(h * 0.30)
        if expected_shift is not None:
            lo = max(lo, min(expected_shift + 8, h - self.strip_h - 8))
        # Per-row variance, then box-filtered over strip_h rows -> variance of each window.
        row_var = gray.astype(np.float32).var(axis=1)
        # Also reward vertical structure: mean abs diff between consecutive rows.
        row_edge = np.abs(np.diff(gray.astype(np.float32), axis=0)).mean(axis=1)
        row_edge = np.concatenate([row_edge, [0.0]])
        score = row_var + 8.0 * row_edge
        kernel = np.ones(self.strip_h, dtype=np.float32) / self.strip_h
        win = np.convolve(score, kernel, mode="valid")  # index i => window [i, i+strip_h)
        win[:lo] = -1
        return int(np.argmax(win))

    def _locate(
        self, prev_gray: np.ndarray, cur_gray: np.ndarray, strip_y: int, expected_shift: int | None
    ) -> tuple[int, float]:
        strip = prev_gray[strip_y : strip_y + self.strip_h]
        res = cv2.matchTemplate(cur_gray, strip, cv2.TM_CCOEFF_NORMED)[:, 0]
        # The strip at prev y appears at cur y' = strip_y - shift, shift >= 0.
        allowed = np.zeros_like(res, dtype=bool)
        if expected_shift is not None:
            lo = strip_y - int(expected_shift * 1.25) - self.search_slack
            hi = strip_y - int(expected_shift * 0.0) + self.search_slack
            allowed[max(0, lo) : min(len(res), hi + 1)] = True
        else:
            allowed[: strip_y + 1] = True
        if not allowed.any():
            allowed[: strip_y + 1] = True
        masked = np.where(allowed, res, -np.inf)
        y = int(np.argmax(masked))
        return strip_y - y, float(masked[y])

    # -- public API -----------------------------------------------------------------

    def add(self, frame: Frame, expected_shift: int | None = None) -> int:
        cur = np.ascontiguousarray(self.region.crop(frame))
        if self._prev is None:
            self._chunks.append(cur.copy())
            self._prev = cur
            self.history.append(StitchResult(cur.shape[0], 1.0, 0))
            return cur.shape[0]

        if np.array_equal(cur, self._prev):
            self.history.append(StitchResult(0, 1.0, -1))
            return 0

        prev_gray = self._gray(self._prev)
        cur_gray = self._gray(cur)
        strip_y = self._pick_strip(prev_gray, expected_shift)
        shift, conf = self._locate(prev_gray, cur_gray, strip_y, expected_shift)

        if conf < self.min_confidence:
            # Retry with an unconstrained search before giving up.
            shift2, conf2 = self._locate(prev_gray, cur_gray, strip_y, None)
            if conf2 > conf:
                shift, conf = shift2, conf2
        if conf < self.min_confidence or shift < 0:
            raise StitchFailed(
                f"Could not align frames (best confidence {conf:.3f}, shift {shift}). "
                "Do not move the mouse or the WeChat window during capture."
            )

        if shift > 0:
            self._chunks.append(cur[cur.shape[0] - shift :].copy())
        self._prev = cur
        self.history.append(StitchResult(shift, conf, strip_y))
        return shift

    def image(self) -> Frame:
        if not self._chunks:
            raise StitchFailed("No frames added.")
        return np.vstack(self._chunks)

    @property
    def height(self) -> int:
        return sum(c.shape[0] for c in self._chunks)

"""Locate the scrollable message area purely from pixels.

WeChat 4.x renders its own UI and exposes no accessibility information for the
message list, so we discover it empirically:

1. capture, scroll a little, capture again; the bounding box of pixels that changed
   is (part of) the message list;
2. grow that box outwards while the surrounding rows/columns are still the message
   panel's background colour, which stops at the header separator, the input box
   border and the chat-list divider.
"""

from __future__ import annotations

import cv2
import numpy as np

from .errors import RegionNotFound
from .types import CaptureFn, Frame, Rect, ScrollFn

_DIFF_THRESHOLD = 24  # per-pixel abs difference (max over channels) to count as "changed"
_BG_TOLERANCE = 6  # max channel distance from the panel background colour (flat fill)
_BG_ROW_FRACTION = 0.985  # fraction of a row/column that must be background to keep growing
_MIN_CHANGED_FRACTION = 0.02
_SCROLLBAR_FRACTION = 0.013  # WeChat's overlay scrollbar hugs the right edge (~6 pt)


def _changed_mask(a: Frame, b: Frame) -> np.ndarray:
    d = np.abs(a.astype(np.int16) - b.astype(np.int16)).max(axis=2)
    return d > _DIFF_THRESHOLD


def _drop_small_components(mask: np.ndarray, min_w: int, min_h: int) -> np.ndarray:
    """Remove changed blobs that are tiny in *both* dimensions (the blinking text caret,
    an unread badge, a hover highlight edge) so they cannot stretch the bounding box."""
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    keep = np.zeros(n, dtype=bool)
    for i in range(1, n):
        w, h = stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
        keep[i] = w >= min_w or h >= min_h
    return keep[labels]


def _bbox(mask: np.ndarray) -> Rect | None:
    ys = np.flatnonzero(mask.any(axis=1))
    xs = np.flatnonzero(mask.any(axis=0))
    if ys.size == 0 or xs.size == 0:
        return None
    return Rect(int(xs[0]), int(ys[0]), int(xs[-1] - xs[0] + 1), int(ys[-1] - ys[0] + 1))


def _dominant_colour(img: Frame) -> np.ndarray:
    """Most frequent colour (quantised to 4 levels) inside ``img``, returned as exact BGR."""
    q = (img >> 2).reshape(-1, 3)
    keys = q[:, 0].astype(np.int32) * 4096 + q[:, 1].astype(np.int32) * 64 + q[:, 2]
    vals, counts = np.unique(keys, return_counts=True)
    key = vals[np.argmax(counts)]
    sel = keys == key
    return np.median(img.reshape(-1, 3)[sel], axis=0).astype(np.int16)


def _is_bg_line(line: np.ndarray, bg: np.ndarray) -> bool:
    dist = np.abs(line.astype(np.int16) - bg).max(axis=1)
    return float((dist <= _BG_TOLERANCE).mean()) >= _BG_ROW_FRACTION


def grow_to_background(frame: Frame, seed: Rect, bg: np.ndarray | None = None) -> Rect:
    """Expand ``seed`` while the neighbouring rows/columns are (almost) pure background."""
    h, w = frame.shape[:2]
    if bg is None:
        bg = _dominant_colour(seed.crop(frame))
    x1, y1, x2, y2 = seed.x, seed.y, seed.x2, seed.y2

    while y1 > 0 and _is_bg_line(frame[y1 - 1, x1:x2], bg):
        y1 -= 1
    while y2 < h and _is_bg_line(frame[y2, x1:x2], bg):
        y2 += 1
    while x1 > 0 and _is_bg_line(frame[y1:y2, x1 - 1], bg):
        x1 -= 1
    while x2 < w and _is_bg_line(frame[y1:y2, x2], bg):
        x2 += 1
    return Rect(x1, y1, x2 - x1, y2 - y1)


def _shrink_seed(frame: Frame, box: Rect, bg: np.ndarray) -> Rect:
    """The diff bbox may include a scrollbar thumb on the far right; trim non-bg-bounded
    columns at the edges that are too thin to be content."""
    # Trim right columns that changed but are isolated (scrollbar): keep it simple —
    # if the rightmost 3 % of the box is background in the still frame, drop it.
    trim = max(1, int(box.w * 0.03))
    right = frame[box.y : box.y2, box.x2 - trim : box.x2]
    if _is_bg_line(right.reshape(-1, 3), bg):
        return Rect(box.x, box.y, box.w - trim, box.h)
    return box


def trim_static_edges(base: Frame, moved: Frame, region: Rect, bg: np.ndarray) -> Rect:
    """Cut rows at the top/bottom of ``region`` that did not move with the list and are
    not plain background (e.g. an input box or toolbar that slipped into the box)."""
    a = region.crop(base)
    b = region.crop(moved)
    changed_rows = _changed_mask(a, b).any(axis=1)
    bg_rows = np.array([_is_bg_line(row, bg) for row in a])
    static_nonbg = ~changed_rows & ~bg_rows
    y1, y2 = 0, region.h
    while y2 > y1 and static_nonbg[y2 - 1]:
        y2 -= 1
    while y1 < y2 and static_nonbg[y1]:
        y1 += 1
    return Rect(region.x, region.y + y1, region.w, y2 - y1)


def detect_message_region(
    capture: CaptureFn, scroll: ScrollFn, frame_hint: Frame | None = None, probe_px: int = 160
) -> Rect:
    """Find the message list rectangle (image pixels). ``scroll`` must return the settled frame."""
    base = frame_hint if frame_hint is not None else capture()
    h, w = base.shape[:2]

    # Try scrolling up first (older content almost always exists), then down.
    moved: Frame | None = None
    for delta in (-probe_px, probe_px):
        cand = scroll(delta)
        mask = _changed_mask(base, cand)
        if mask.mean() >= _MIN_CHANGED_FRACTION:
            moved = cand
            scroll(-delta)  # restore
            break
        base = cand
    if moved is None:
        raise RegionNotFound(
            "Scrolling did not change the window content; is a chat open and does it "
            "have more than one screen of messages? Use --region X,Y,W,H to override."
        )

    mask = _changed_mask(base, moved)
    # Ignore anything in the left 30 % of the window (chat list previews can change
    # when new messages arrive) and the top 5 % (title bar).
    mask[:, : int(w * 0.30)] = False
    mask[: int(h * 0.05), :] = False
    mask = _drop_small_components(mask, min_w=int(w * 0.02), min_h=int(h * 0.04))
    box = _bbox(mask)
    if box is None:
        raise RegionNotFound("No changed pixels inside the expected message-panel area.")

    bg = _dominant_colour(box.crop(base))
    box = _shrink_seed(base, box, bg)
    region = grow_to_background(base, box, bg)
    margin = int(region.w * _SCROLLBAR_FRACTION)
    region = Rect(region.x, region.y, region.w - margin, region.h)
    region = trim_static_edges(base, moved, region, bg)
    if region.w < w * 0.3 or region.h < h * 0.3:
        raise RegionNotFound(
            f"Detected region {region} looks too small; pass --region to override."
        )
    return region

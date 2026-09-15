"""Scroll the list to where the long screenshot should begin."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime

from .ocr import recognize_text
from .scroller import Scroller
from .timeparse import parse_time_label
from .types import Frame, Rect, TextBox, TimeLabel

log = logging.getLogger(__name__)

# WeChat centres its time separators in the message column; genuine messages are
# left/right aligned. This filter rejects OCR hits inside bubbles ("明天 10:00 见").
_CENTER_TOLERANCE = 0.12
_MAX_LABEL_CHARS = 24


@dataclass
class StartPoint:
    frame: Frame
    crop_y: int | None  # region-relative row where content should start (None = whole frame)
    label: TimeLabel | None
    reached_top: bool


def find_time_labels(frame: Frame, region: Rect, now: datetime) -> list[TimeLabel]:
    crop = region.crop(frame)
    labels: list[TimeLabel] = []
    cx = region.w / 2
    for tb in recognize_text(crop):
        if len(tb.text) > _MAX_LABEL_CHARS:
            continue
        if abs(tb.rect.center[0] - cx) > region.w * _CENTER_TOLERANCE:
            continue
        when = parse_time_label(tb.text, now)
        if when is None:
            continue
        labels.append(TimeLabel(when, TextBox(tb.text, tb.rect, tb.confidence)))
    return labels


def navigate_to_start(
    scroller: Scroller,
    start: datetime | None,
    now: datetime,
    max_pages: int = 2000,
    top_retries: int = 3,
) -> StartPoint:
    """Scroll up until a time separator <= ``start`` is visible (or the top is reached).

    With ``start=None`` the current view is used as-is.
    """
    region = scroller.region
    assert region is not None, "region must be detected before navigating"
    frame = scroller.settle()
    if start is None:
        return StartPoint(frame, None, None, False)

    stuck = 0
    for page in range(max_pages):
        labels = find_time_labels(frame, region, now)
        older = [lb for lb in labels if lb.when <= start]
        if older:
            best = max(older, key=lambda lb: lb.when)
            log.info("start separator %r (%s) found after %d pages", best.box.text, best.when, page)
            return StartPoint(frame, max(0, best.box.rect.y - 8), best, False)

        prev = frame
        frame = scroller.page_up(0.7)
        if _same(prev, frame, region):
            stuck += 1
            if stuck > top_retries:
                log.info("reached top of history after %d pages", page)
                return StartPoint(frame, None, None, True)
            time.sleep(0.8)  # give WeChat time to lazy-load older history
            frame = scroller.settle()
        else:
            stuck = 0
    return StartPoint(frame, None, None, True)


def _same(a: Frame, b: Frame, region: Rect) -> bool:
    import numpy as np

    return bool(np.array_equal(region.crop(a), region.crop(b)))

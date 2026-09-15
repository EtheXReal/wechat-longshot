"""Scroll the list to where the long screenshot should begin."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cv2

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
    debug_dir: Path | None = None,
) -> StartPoint:
    """Scroll until the *last* time separator ``<= start`` is on screen.

    The view may currently be newer or older than ``start`` (the user, or a previous
    run, may have left it anywhere), so this walks in whichever direction is needed:

    * all visible labels are newer than ``start``  -> page up (older)
    * all visible labels are older/equal           -> page down (newer) until a newer
      label shows up or the bottom is hit, then the boundary is the newest label
      ``<= start`` seen in the last two (overlapping) frames
    * both kinds visible                           -> done

    With ``start=None`` the current view is used as-is.
    """
    region = scroller.region
    assert region is not None, "region must be detected before navigating"
    frame = scroller.settle()
    if start is None:
        return StartPoint(frame, None, None, False)

    def labels_of(fr: Frame, page: int) -> list[TimeLabel]:
        labs = find_time_labels(fr, region, now)
        log.info("nav page %d: %s", page, [lb.box.text for lb in labs])
        if debug_dir is not None:
            debug_dir.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(debug_dir / f"nav_{page:03d}.png"), region.crop(fr))
        return labs

    def boundary(labs: list[TimeLabel]) -> TimeLabel | None:
        older = [lb for lb in labs if lb.when <= start]
        return max(older, key=lambda lb: lb.when) if older else None

    seen_newer = seen_older = False
    direction = -1  # -1 = towards older (page up), +1 = towards newer (page down)
    fraction = 0.7
    stuck = 0
    for page in range(max_pages):
        labels = labels_of(frame, page)
        has_newer = any(lb.when > start for lb in labels)
        has_older = any(lb.when <= start for lb in labels)

        if has_older and (has_newer or seen_newer):
            # Bracketed: the newest label <= start on this screen is the boundary.
            return _at(frame, boundary(labels), page)
        if has_older:
            seen_older, direction, fraction = True, +1, 0.7
        elif has_newer:
            # Coming up from the older side we overshot: back-track in small steps.
            direction, fraction = -1, (0.35 if seen_older else 0.7)
            seen_newer = True
        # No labels at all: keep going the way we were going.

        prev = frame
        frame = scroller.page_down(fraction) if direction > 0 else scroller.page_up(fraction)
        if not _same(prev, frame, region):
            stuck = 0
            continue
        stuck += 1
        if direction > 0:
            log.info("bottom of chat reached while looking for %s", start)
            return _at(frame, boundary(labels), page)
        if stuck > top_retries:
            log.info("reached top of history after %d pages", page)
            return StartPoint(frame, None, None, True)
        time.sleep(0.8)  # give WeChat time to lazy-load older history
        frame = scroller.settle()
    return StartPoint(frame, None, None, True)


def _at(frame: Frame, label: TimeLabel | None, page: int) -> StartPoint:
    if label is None:
        return StartPoint(frame, None, None, False)
    log.info("start separator %r (%s) found after %d pages", label.box.text, label.when, page)
    return StartPoint(frame, max(0, label.box.rect.y - 8), label, False)


def _same(a: Frame, b: Frame, region: Rect) -> bool:
    import numpy as np

    return bool(np.array_equal(region.crop(a), region.crop(b)))

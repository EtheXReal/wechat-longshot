"""End-to-end: find window -> region -> navigate -> capture/stitch -> PDF."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

import cv2

from .errors import StitchFailed
from .navigator import navigate_to_start
from .pdf import image_to_pdf
from .region import detect_message_region
from .scroller import Scroller
from .stitcher import Stitcher, measure_shift
from .types import Frame, Rect
from .window import activate_window, capture_window, find_wechat_window

log = logging.getLogger(__name__)


@dataclass
class Options:
    start: datetime | None
    out: Path
    page_mode: Literal["long", "a4"] = "long"
    region: Rect | None = None
    step_fraction: float = 0.6
    max_pages: int = 500
    keep_png: bool = False
    debug_dir: Path | None = None
    now: datetime = field(default_factory=datetime.now)


def calibrate_scroll(scroller: Scroller, request_px: int = 300) -> float:
    """Measure how far WeChat really scrolls per requested pixel and store it on the scroller."""
    region = scroller.region
    assert region is not None
    before = scroller.settle()
    after = scroller.scroll(-request_px)
    shift, conf = measure_shift(before, after, region)
    scroller.scroll(request_px)
    if conf < 0.9 or shift >= 0:
        log.warning(
            "scroll calibration inconclusive (shift=%d conf=%.2f); using gain 1.5", shift, conf
        )
        scroller.gain = 1.5
    else:
        scroller.gain = -shift / request_px
    log.info("scroll gain = %.3f", scroller.gain)
    return scroller.gain


def _dump(debug_dir: Path | None, name: str, img: Frame) -> None:
    if debug_dir is not None:
        debug_dir.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(debug_dir / name), img)


def capture_long_image(opts: Options) -> Frame:
    win = find_wechat_window()
    log.info(
        "WeChat window %d at (%.0f,%.0f) %.0fx%.0f @%.1fx",
        win.window_id,
        win.x,
        win.y,
        win.width,
        win.height,
        win.scale,
    )
    activate_window(win)

    def capture() -> Frame:
        return capture_window(win)

    scroller = Scroller(win, opts.region, capture)
    region = opts.region or detect_message_region(capture, scroller.scroll)
    scroller.region = region
    log.info("message region: %s", region)
    first = scroller.settle()
    dbg = first.copy()
    cv2.rectangle(dbg, (region.x, region.y), (region.x2, region.y2), (0, 0, 255), 3)
    _dump(opts.debug_dir, "region.png", dbg)

    calibrate_scroll(scroller)

    sp = navigate_to_start(scroller, opts.start, opts.now, debug_dir=opts.debug_dir)
    stitcher = Stitcher(region)
    stitcher.add(sp.frame)
    _dump(opts.debug_dir, "page_000.png", region.crop(sp.frame))

    step = int(region.h * opts.step_fraction)
    for i in range(1, opts.max_pages + 1):
        frame = scroller.scroll(step)
        try:
            shift = stitcher.add(frame, expected_shift=step)
        except StitchFailed:
            # Retry once with a half step; WeChat occasionally re-lays out while loading media.
            log.warning("alignment failed on page %d, retrying with a smaller step", i)
            frame = scroller.scroll(-step // 2)
            shift = stitcher.add(frame, expected_shift=None)
        _dump(opts.debug_dir, f"page_{i:03d}.png", region.crop(frame))
        log.info("page %d: +%d px (total %d)", i, shift, stitcher.height)
        if shift == 0:
            # Bottom reached; give a newly arrived message a chance, then stop.
            time.sleep(0.3)
            if stitcher.add(scroller.settle(), expected_shift=None) == 0:
                break

    tall = stitcher.image()
    if sp.crop_y:
        tall = tall[sp.crop_y :]
    return tall


def run(opts: Options) -> Path:
    tall = capture_long_image(opts)
    opts.out.parent.mkdir(parents=True, exist_ok=True)
    if opts.keep_png:
        cv2.imwrite(str(opts.out.with_suffix(".png")), tall)
    image_to_pdf(tall, opts.out, page_mode=opts.page_mode)
    log.info("wrote %s (%dx%d px)", opts.out, tall.shape[1], tall.shape[0])
    return opts.out

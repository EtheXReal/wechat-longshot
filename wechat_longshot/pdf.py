"""Write the stitched long image out as a PDF."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Literal

import numpy as np
from PIL import Image

from .types import Frame

__all__ = ["image_to_pdf"]

#: Hard limit of the PDF format: no page may exceed 14400 pt (200 inch) a side.
MAX_PAGE_PT = 14400

#: A4 aspect ratio (height / width) in portrait orientation.
A4_RATIO = 297 / 210

#: How far around the ideal A4 cut we look for a quiet (uniform) row.
CUT_SEARCH_FRACTION = 0.08

#: Rows within this much of the quietest one count as equally quiet.
NOISE_TOLERANCE = 0.5


def _pt_to_px(points: float, dpi: int) -> int:
    return int(points * dpi / 72)


def _row_noise(image: Frame) -> np.ndarray:
    """Per-row standard deviation of a BGR image (low => uniform background row)."""
    gray = image.astype(np.float32).mean(axis=2)
    return gray.std(axis=1)


def _quiet_row(noise: np.ndarray, ideal: int, radius: int, lo: int, hi: int) -> int:
    """Quietest row within ``radius`` of ``ideal``, clamped to ``[lo, hi)``.

    Rows that are equally quiet (a uniform background gives a whole run of them)
    are broken in favour of the one closest to ``ideal``, so pages stay the size
    they were asked for instead of drifting shorter with every cut.
    """
    start = max(lo, ideal - radius)
    stop = min(hi, ideal + radius + 1)
    if stop <= start:
        return max(lo, min(ideal, hi - 1))
    window = noise[start:stop]
    quiet = np.flatnonzero(window <= window.min() + NOISE_TOLERANCE)
    return start + int(quiet[np.argmin(np.abs(quiet + start - ideal))])


def _cut_rows_a4(image: Frame) -> list[int]:
    """Cut points for A4 pages, nudged onto uniform background rows."""
    height, width = image.shape[:2]
    page_h = max(1, int(round(width * A4_RATIO)))
    if height <= page_h:
        return [height]

    noise = _row_noise(image)
    radius = max(1, int(page_h * CUT_SEARCH_FRACTION))
    cuts: list[int] = []
    start = 0
    while height - start > page_h:
        ideal = start + page_h
        # never let the nudge produce an empty or oversized page
        cut = _quiet_row(noise, ideal, radius, lo=start + 1, hi=height)
        cut = max(start + 1, min(cut, height - 1))
        cuts.append(cut)
        start = cut
    cuts.append(height)
    return cuts


def _cut_rows_long(image: Frame, dpi: int) -> list[int]:
    """One page, split only when the 14400 pt page limit forces it."""
    height = image.shape[0]
    max_rows = max(1, _pt_to_px(MAX_PAGE_PT, dpi))
    if height <= max_rows:
        return [height]
    pages = math.ceil(height / max_rows)
    rows = math.ceil(height / pages)
    return [min(height, rows * (i + 1)) for i in range(pages)]


def image_to_pdf(
    image: Frame,
    out: Path,
    page_mode: Literal["long", "a4"] = "long",
    dpi: int = 144,
) -> None:
    """Render a tall BGR image to ``out`` as a PDF.

    ``page_mode="long"`` keeps everything on a single page, splitting only if the
    PDF page-size limit is exceeded. ``page_mode="a4"`` slices it into A4-shaped
    pages whose cut rows are moved to the quietest (most uniform) nearby row, so
    chat bubbles are not sliced in half.
    """
    if image is None or image.size == 0:
        raise ValueError("image_to_pdf: empty image")
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError(f"image_to_pdf: expected an (H, W, 3) BGR image, got {image.shape}")
    if dpi <= 0:
        raise ValueError("image_to_pdf: dpi must be positive")

    if page_mode == "a4":
        cuts = _cut_rows_a4(image)
    elif page_mode == "long":
        cuts = _cut_rows_long(image, dpi)
    else:
        raise ValueError(f"image_to_pdf: unknown page_mode {page_mode!r}")

    rgb = image[:, :, ::-1]
    pages: list[Image.Image] = []
    start = 0
    for cut in cuts:
        pages.append(Image.fromarray(np.ascontiguousarray(rgb[start:cut])).convert("RGB"))
        start = cut

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pages[0].save(
        out,
        "PDF",
        resolution=float(dpi),
        save_all=True,
        append_images=pages[1:],
    )

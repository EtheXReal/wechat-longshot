import numpy as np
import pytest

from wechat_longshot.errors import StitchFailed
from wechat_longshot.stitcher import Stitcher, measure_shift
from wechat_longshot.types import Rect


def _document(height: int = 6000, width: int = 400, seed: int = 0) -> np.ndarray:
    """A tall synthetic 'chat': grey background with random coloured bubbles."""
    rng = np.random.default_rng(seed)
    doc = np.full((height, width, 3), 245, np.uint8)
    y = 10
    while y < height - 80:
        h = int(rng.integers(30, 90))
        x = int(rng.integers(20, width - 150))
        colour = rng.integers(0, 200, 3)
        doc[y : y + h, x : x + 120] = colour
        # non-periodic "text" texture inside the bubble
        noise = rng.integers(0, 256, (max(1, h - 10), 110, 3), dtype=np.uint8)
        doc[y + 5 : y + h - 5, x + 5 : x + 115] = noise[: max(0, h - 10)]
        y += h + int(rng.integers(10, 60))
    return doc


def _viewport(doc: np.ndarray, top: int, view_h: int) -> np.ndarray:
    top = max(0, min(top, doc.shape[0] - view_h))
    return doc[top : top + view_h]


def test_stitch_reconstructs_document_exactly():
    doc = _document()
    view_h = 800
    region = Rect(0, 0, doc.shape[1], view_h)
    st = Stitcher(region)
    top = 0
    st.add(_viewport(doc, top, view_h))
    step = int(view_h * 0.6)
    while True:
        top += step + int(np.random.default_rng(top).integers(-40, 40))  # imprecise scrolling
        frame = _viewport(doc, top, view_h)
        shift = st.add(frame, expected_shift=step)
        if shift == 0:
            break
    out = st.image()
    assert out.shape == doc.shape
    assert np.array_equal(out, doc)


def test_measure_shift():
    doc = _document()
    view_h = 800
    region = Rect(0, 0, doc.shape[1], view_h)
    a = _viewport(doc, 1000, view_h)
    b = _viewport(doc, 1237, view_h)
    shift, conf = measure_shift(a, b, region)
    assert shift == 237
    assert conf > 0.95


def test_unrelated_frames_raise():
    view_h = 800
    region = Rect(0, 0, 400, view_h)
    st = Stitcher(region)
    st.add(_viewport(_document(seed=1), 0, view_h))
    with pytest.raises(StitchFailed):
        st.add(_viewport(_document(seed=2), 3000, view_h), expected_shift=480)

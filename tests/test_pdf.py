"""Tests for :mod:`wechat_longshot.pdf` using synthetic chat-like images."""

from __future__ import annotations

import numpy as np
import pytest

from wechat_longshot.pdf import MAX_PAGE_PT, _cut_rows_a4, image_to_pdf

BG = 240  # uniform "chat background" grey


def make_image(
    height: int, width: int = 400, bubbles: list[tuple[int, int]] | None = None
) -> np.ndarray:
    """Grey background with dark rectangles ("bubbles") at the given row ranges."""
    img = np.full((height, width, 3), BG, dtype=np.uint8)
    for top, bottom in bubbles or []:
        img[top:bottom, 40 : width - 40] = (30, 60, 90)
    return img


def page_sizes(path) -> list[tuple[float, float]]:
    """Page sizes in points, read back from the written PDF."""
    data = path.read_bytes()
    boxes = []
    for chunk in data.split(b"/MediaBox")[1:]:
        nums = chunk.split(b"[")[1].split(b"]")[0].split()
        boxes.append((float(nums[2]), float(nums[3])))
    return boxes


def test_long_mode_single_page(tmp_path):
    out = tmp_path / "chat.pdf"
    image_to_pdf(make_image(2000), out, page_mode="long", dpi=144)
    assert out.exists()
    sizes = page_sizes(out)
    assert len(sizes) == 1
    assert sizes[0] == pytest.approx((400 * 72 / 144, 2000 * 72 / 144), abs=1.0)


def test_long_mode_splits_at_the_pdf_page_limit(tmp_path):
    dpi = 144
    max_rows = int(MAX_PAGE_PT * dpi / 72)  # 28800 px at 144 dpi
    out = tmp_path / "tall.pdf"
    image_to_pdf(make_image(max_rows + 1000, width=50), out, page_mode="long", dpi=dpi)
    sizes = page_sizes(out)
    assert len(sizes) == 2
    assert all(h <= MAX_PAGE_PT + 1 for _, h in sizes)


def test_long_mode_splits_into_three_pages(tmp_path):
    dpi = 144
    max_rows = int(MAX_PAGE_PT * dpi / 72)
    out = tmp_path / "taller.pdf"
    image_to_pdf(make_image(max_rows * 2 + 10, width=50), out, page_mode="long", dpi=dpi)
    assert len(page_sizes(out)) == 3


def test_a4_page_count_and_aspect(tmp_path):
    width = 400
    page_h = round(width * 297 / 210)  # ~566
    out = tmp_path / "a4.pdf"
    image_to_pdf(make_image(page_h * 3, width), out, page_mode="a4", dpi=144)
    sizes = page_sizes(out)
    assert len(sizes) == 3
    for w, h in sizes[:-1]:
        assert h / w == pytest.approx(297 / 210, rel=0.1)


def test_a4_short_image_is_one_page(tmp_path):
    out = tmp_path / "short.pdf"
    image_to_pdf(make_image(100, 400), out, page_mode="a4", dpi=144)
    assert len(page_sizes(out)) == 1


def test_a4_cut_avoids_slicing_a_bubble():
    width = 400
    page_h = round(width * 297 / 210)
    # A bubble sits exactly on the ideal cut row; the search must step around it.
    bubble = (page_h - 30, page_h + 30)
    img = make_image(page_h * 2, width, bubbles=[(60, 160), bubble, (page_h + 200, page_h + 300)])
    cuts = _cut_rows_a4(img)
    cut = cuts[0]
    assert not (bubble[0] <= cut < bubble[1]), f"cut {cut} landed inside the bubble {bubble}"
    # and it landed on a genuinely uniform row
    assert img[cut].std() == pytest.approx(0.0, abs=1e-6)


def test_a4_cut_stays_within_the_search_window():
    width = 400
    page_h = round(width * 297 / 210)
    img = make_image(page_h * 2, width, bubbles=[(page_h - 40, page_h + 40)])
    cut = _cut_rows_a4(img)[0]
    assert abs(cut - page_h) <= int(page_h * 0.08) + 1


def test_a4_cuts_cover_the_whole_image():
    img = make_image(1800, 400, bubbles=[(100, 200), (500, 700), (1200, 1300)])
    cuts = _cut_rows_a4(img)
    assert cuts[-1] == img.shape[0]
    assert all(b > a for a, b in zip(cuts, cuts[1:], strict=False))


def test_writes_a_pdf_header(tmp_path):
    img = np.zeros((50, 50, 3), dtype=np.uint8)
    img[:, :, 2] = 255  # pure red in BGR
    out = tmp_path / "red.pdf"
    image_to_pdf(img, out, page_mode="long", dpi=72)
    assert out.read_bytes().startswith(b"%PDF")


@pytest.mark.parametrize(
    ("kwargs", "image"),
    [
        ({}, np.zeros((0, 0, 3), dtype=np.uint8)),
        ({}, np.zeros((10, 10), dtype=np.uint8)),
        ({"page_mode": "letter"}, np.zeros((10, 10, 3), dtype=np.uint8)),
        ({"dpi": 0}, np.zeros((10, 10, 3), dtype=np.uint8)),
    ],
)
def test_invalid_input_raises(tmp_path, kwargs, image):
    with pytest.raises(ValueError):
        image_to_pdf(image, tmp_path / "x.pdf", **kwargs)

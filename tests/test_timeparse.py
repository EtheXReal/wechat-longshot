"""Tests for :mod:`wechat_longshot.timeparse` against a fixed ``now``."""

from __future__ import annotations

from datetime import datetime

import pytest

from wechat_longshot.timeparse import parse_time_label

# Wednesday, 2026-09-16 15:04:05
NOW = datetime(2026, 9, 16, 15, 4, 5)


def p(text: str) -> datetime | None:
    return parse_time_label(text, NOW)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("14:38", datetime(2026, 9, 16, 14, 38)),
        ("09:05", datetime(2026, 9, 16, 9, 5)),
        ("0:00", datetime(2026, 9, 16, 0, 0)),
        ("23:59", datetime(2026, 9, 16, 23, 59)),
        ("14:38:20", datetime(2026, 9, 16, 14, 38, 20)),
    ],
)
def test_bare_time_is_today(text: str, expected: datetime) -> None:
    assert p(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("上午 9:05", datetime(2026, 9, 16, 9, 5)),
        ("上午9:05", datetime(2026, 9, 16, 9, 5)),
        ("早上 7:30", datetime(2026, 9, 16, 7, 30)),
        ("凌晨 2:15", datetime(2026, 9, 16, 2, 15)),
        ("中午 12:00", datetime(2026, 9, 16, 12, 0)),
        ("下午 3:20", datetime(2026, 9, 16, 15, 20)),
        ("下午 12:30", datetime(2026, 9, 16, 12, 30)),
        ("晚上 8:45", datetime(2026, 9, 16, 20, 45)),
        ("上午 12:10", datetime(2026, 9, 16, 0, 10)),
        ("9:05 AM", datetime(2026, 9, 16, 9, 5)),
        ("3:20 PM", datetime(2026, 9, 16, 15, 20)),
        ("3:20pm", datetime(2026, 9, 16, 15, 20)),
        ("12:30 a.m.", datetime(2026, 9, 16, 0, 30)),
        ("12:30 p.m.", datetime(2026, 9, 16, 12, 30)),
    ],
)
def test_twelve_hour_prefixes(text: str, expected: datetime) -> None:
    assert p(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("昨天 14:38", datetime(2026, 9, 15, 14, 38)),
        ("昨天14:38", datetime(2026, 9, 15, 14, 38)),
        ("Yesterday 14:38", datetime(2026, 9, 15, 14, 38)),
        ("yesterday 2:05 PM", datetime(2026, 9, 15, 14, 5)),
        ("前天 08:00", datetime(2026, 9, 14, 8, 0)),
        ("今天 10:00", datetime(2026, 9, 16, 10, 0)),
        ("昨天 下午 3:20", datetime(2026, 9, 15, 15, 20)),
    ],
)
def test_relative_days(text: str, expected: datetime) -> None:
    assert p(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # NOW is a Wednesday; weekday labels resolve to the most recent past one.
        ("星期五 14:38", datetime(2026, 9, 11, 14, 38)),
        ("周五 14:38", datetime(2026, 9, 11, 14, 38)),
        ("礼拜五 14:38", datetime(2026, 9, 11, 14, 38)),
        ("星期日 09:00", datetime(2026, 9, 13, 9, 0)),
        ("星期天 09:00", datetime(2026, 9, 13, 9, 0)),
        ("周一 09:00", datetime(2026, 9, 14, 9, 0)),
        ("Friday 14:38", datetime(2026, 9, 11, 14, 38)),
        ("Fri 14:38", datetime(2026, 9, 11, 14, 38)),
        ("Sunday 9:00 AM", datetime(2026, 9, 13, 9, 0)),
        # the same weekday as today means a week ago, never today
        ("星期三 08:00", datetime(2026, 9, 9, 8, 0)),
        ("Wednesday 08:00", datetime(2026, 9, 9, 8, 0)),
    ],
)
def test_weekdays(text: str, expected: datetime) -> None:
    assert p(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("9/3 22:13", datetime(2026, 9, 3, 22, 13)),
        ("2025/9/3 22:13", datetime(2025, 9, 3, 22, 13)),
        ("2025-09-03 22:13", datetime(2025, 9, 3, 22, 13)),
        ("2025年9月3日 22:13", datetime(2025, 9, 3, 22, 13)),
        ("9月3日 22:13", datetime(2026, 9, 3, 22, 13)),
        ("9月3日22:13", datetime(2026, 9, 3, 22, 13)),
        ("2025年9月3日 下午10:13", datetime(2025, 9, 3, 22, 13)),
        # bare dates are separators too
        ("9月3日", datetime(2026, 9, 3, 0, 0)),
        ("2025/9/3", datetime(2025, 9, 3, 0, 0)),
    ],
)
def test_dates(text: str, expected: datetime) -> None:
    assert p(text) == expected


def test_month_day_rolls_back_a_year_when_in_the_future() -> None:
    # NOW is 2026-09-16, so 12/25 must be last year's.
    assert p("12/25 10:00") == datetime(2025, 12, 25, 10, 0)
    assert p("12月25日 10:00") == datetime(2025, 12, 25, 10, 0)
    # ...but a date earlier this year stays in the current year.
    assert p("1/2 10:00") == datetime(2026, 1, 2, 10, 0)


def test_month_day_today_stays_today() -> None:
    assert p("9/16 08:00") == datetime(2026, 9, 16, 8, 0)


@pytest.mark.parametrize(
    "text",
    [
        "14：38",  # full-width colon
        "  14:38  ",  # padding
        "昨天　14:38",  # ideographic space
        "2025年9月3日  22:13",
        "Friday, 14:38",
    ],
)
def test_ocr_noise_is_tolerated(text: str) -> None:
    assert p(text) is not None


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "10点见",
        "明天见",
        "https://example.com/a/12:30",
        "12:30 见面",
        "会议 14:38 开始",
        "撤回了一条消息",
        "[图片]",
        "1234",
        "99:99",
        "25:00",
        "14:60",
        "下午 13:20",  # 12h marker with an out-of-range hour
        "2025年2月30日 10:00",  # impossible date
        "13/45 10:00",  # not a month/day
        "Funday 14:38",
        "转账 9/3",
        "上午",
    ],
)
def test_non_time_labels_return_none(text: str) -> None:
    assert p(text) is None

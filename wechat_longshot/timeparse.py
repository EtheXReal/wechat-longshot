"""Parse WeChat time separators (zh-CN / en-US) into ``datetime``.

Pure Python, no OCR. The input is whatever Vision read off a separator label, so
the parser tolerates typical OCR noise (full-width colon, stray spaces) but is
deliberately strict about the *shape* of the string: the whole label must be a
date/time expression, otherwise ``None`` is returned. That keeps ordinary
messages ("10点见", a URL, "价格 9/3 折") from being mistaken for separators.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta

__all__ = ["parse_time_label"]

# ---------------------------------------------------------------------------
# vocabulary

_ZH_WEEKDAYS = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
_EN_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
_EN_WEEKDAYS.update({name[:3]: idx for name, idx in list(_EN_WEEKDAYS.items())})

# zh day-part prefixes -> how to fold a 1..12 hour into 24h
_ZH_DAYPARTS = {
    "凌晨": "am",
    "早上": "am",
    "早晨": "am",
    "上午": "am",
    "中午": "noon",
    "下午": "pm",
    "傍晚": "pm",
    "晚上": "pm",
    "晚": "pm",
    "夜里": "night",
    "半夜": "night",
}

_REL_DAYS = {
    "今天": 0,
    "今日": 0,
    "today": 0,
    "昨天": 1,
    "昨日": 1,
    "yesterday": 1,
    "前天": 2,
    "the day before yesterday": 2,
}

# ---------------------------------------------------------------------------
# regexes

_DAYPART = "|".join(sorted(_ZH_DAYPARTS, key=len, reverse=True))
_REL = "|".join(sorted((re.escape(k) for k in _REL_DAYS), key=len, reverse=True))
_ZH_WD = "(?:星期|週|周|礼拜|禮拜)([一二三四五六日天])"
_EN_WD = "|".join(sorted(_EN_WEEKDAYS, key=len, reverse=True))

_DATE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(rf"(?i)^(?:{_REL})$"), "rel"),
    (re.compile(rf"^{_ZH_WD}$"), "zh_wd"),
    (re.compile(rf"(?i)^({_EN_WD})$"), "en_wd"),
    (re.compile(r"^(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})$"), "ymd"),
    (re.compile(r"^(\d{4})年(\d{1,2})月(\d{1,2})日?$"), "ymd"),
    (re.compile(r"^(\d{1,2})月(\d{1,2})日?$"), "md"),
    (re.compile(r"^(\d{1,2})[/\-](\d{1,2})$"), "md"),
]

_TIME_RE = re.compile(
    r"(?i)^"
    r"(?:(?P<zh>" + _DAYPART + r")\s*)?"
    r"(?:(?P<am_pre>am|pm)\s*)?"
    r"(?P<h>\d{1,2}):(?P<m>\d{2})(?::(?P<s>\d{2}))?"
    r"\s*(?P<am_post>am|pm)?"
    r"$"
)


def _normalize(text: str) -> str:
    """Fold OCR noise: full-width forms, odd colons/spaces, trailing punctuation."""
    s = unicodedata.normalize("NFKC", text)
    s = s.replace("：", ":").replace("﹕", ":").replace("∶", ":")
    s = s.replace(" ", " ").replace("　", " ")
    s = s.replace("a.m.", "am").replace("A.M.", "AM")
    s = s.replace("p.m.", "pm").replace("P.M.", "PM")
    s = re.sub(r"[,，、]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s.strip(" ·-—")


def _split(s: str) -> tuple[str | None, str | None]:
    """Split a normalized label into (date part, time part).

    The time part is the trailing ``H:MM`` run together with any day-part word
    or am/pm marker glued to it; everything before it is the date part.
    """
    m = re.search(r"\d{1,2}:\d{2}", s)
    if not m:
        return (s or None, None)
    start = m.start()
    # pull a preceding day-part / am-pm word into the time half
    head = s[:start]
    pre = re.search(rf"(?i)((?:{_DAYPART}|am|pm)\s*)$", head)
    if pre:
        start = pre.start(1)
    date_part = s[:start].strip()
    return (date_part or None, s[start:].strip())


def _resolve_date(part: str, now: datetime) -> date | None:
    for pattern, kind in _DATE_PATTERNS:
        m = pattern.match(part)
        if not m:
            continue
        if kind == "rel":
            return now.date() - timedelta(days=_REL_DAYS[m.group(0).lower()])
        if kind == "zh_wd":
            return _back_to_weekday(now.date(), _ZH_WEEKDAYS[m.group(1)])
        if kind == "en_wd":
            return _back_to_weekday(now.date(), _EN_WEEKDAYS[m.group(1).lower()])
        if kind == "ymd":
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                return None
        if kind == "md":
            month, day = int(m.group(1)), int(m.group(2))
            try:
                candidate = date(now.year, month, day)
            except ValueError:
                return None
            if candidate > now.date():
                try:
                    candidate = date(now.year - 1, month, day)
                except ValueError:
                    return None
            return candidate
    return None


def _back_to_weekday(today: date, weekday: int) -> date:
    """Most recent *past* occurrence of ``weekday`` (never today itself)."""
    delta = (today.weekday() - weekday) % 7
    return today - timedelta(days=delta or 7)


def _fold_hour(hour: int, marker: str | None) -> int | None:
    if marker is None:
        return hour if 0 <= hour <= 23 else None
    if not 0 <= hour <= 12:
        return None
    if marker == "am":
        return 0 if hour == 12 else hour
    if marker == "noon":
        return 12 if hour == 12 else (hour + 12 if hour < 12 else hour)
    if marker == "night":
        # 夜里/半夜 11:40 -> 23:40, 夜里 1:00 -> 01:00
        return hour if hour <= 4 else (hour + 12 if hour < 12 else hour)
    # pm
    return hour if hour == 12 else hour + 12


def parse_time_label(text: str, now: datetime) -> datetime | None:
    """Parse a WeChat time separator, or return ``None`` if it isn't one.

    Relative labels (昨天 / Yesterday / weekday names) are resolved against
    ``now``; a bare ``M/D`` uses the current year, or the previous one when that
    would place the label in the future.
    """
    if not text:
        return None
    s = _normalize(text)
    if not s:
        return None

    date_part, time_part = _split(s)

    if time_part is None:
        # a date with no clock time is still a valid separator ("9月3日")
        if date_part is None:
            return None
        resolved = _resolve_date(date_part, now)
        return datetime.combine(resolved, datetime.min.time()) if resolved else None

    tm = _TIME_RE.match(time_part)
    if not tm:
        return None

    marker = None
    if tm.group("zh"):
        marker = _ZH_DAYPARTS[tm.group("zh")]
    elif tm.group("am_pre") or tm.group("am_post"):
        marker = (tm.group("am_pre") or tm.group("am_post")).lower()

    hour = _fold_hour(int(tm.group("h")), marker)
    minute, second = int(tm.group("m")), int(tm.group("s") or 0)
    if hour is None or minute > 59 or second > 59:
        return None

    if date_part is None:
        day = now.date()
    else:
        day = _resolve_date(date_part, now)
        if day is None:
            return None

    return datetime(day.year, day.month, day.day, hour, minute, second)

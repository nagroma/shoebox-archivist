"""Fuzzy dates for historical photos.

Every date is stored as:
  * ``edtf``      - Extended Date/Time Format (ISO 8601-2) string, the canonical value
  * ``date_min``  - earliest possible calendar date (for sorting / filtering)
  * ``date_max``  - latest possible calendar date
  * ``precision`` - day | month | season | year | decade | century | range

``parse()`` accepts free-form text people actually type ("1920s", "c. 1925",
"summer 1948", "May 1923", "1920-1925") as well as EDTF itself.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date

# How far "circa 1925" stretches either side, in years.
APPROX_YEARS = 2

MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})
MONTHS["sept"] = 9

# EDTF level-1 season codes; months are northern hemisphere.
SEASONS = {"spring": (21, 3, 5), "summer": (22, 6, 8), "autumn": (23, 9, 11),
           "fall": (23, 9, 11), "winter": (24, 12, 2)}
SEASON_BY_CODE = {code: (name, start, end) for name, (code, start, end) in SEASONS.items()}

APPROX_WORDS = r"(?:c\.?|ca\.?|circa|about|abt\.?|around|approx\.?|approximately|~)"


@dataclass(frozen=True)
class FuzzyDate:
    edtf: str
    date_min: date
    date_max: date
    precision: str

    def __str__(self) -> str:
        return describe(self)


def _last_day(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def _year_span(y1: int, y2: int) -> tuple[date, date]:
    return date(y1, 1, 1), date(y2, 12, 31)


def _day(y: int, m: int, d: int) -> FuzzyDate:
    dt = date(y, m, d)  # raises ValueError on invalid dates
    return FuzzyDate(f"{y:04d}-{m:02d}-{d:02d}", dt, dt, "day")


def _month(y: int, m: int) -> FuzzyDate:
    if not 1 <= m <= 12:
        raise ValueError(m)
    return FuzzyDate(f"{y:04d}-{m:02d}", date(y, m, 1), date(y, m, _last_day(y, m)), "month")


def _season(y: int, name: str) -> FuzzyDate:
    code, start, end = SEASONS[name]
    end_year = y + 1 if end < start else y
    return FuzzyDate(f"{y:04d}-{code}", date(y, start, 1),
                     date(end_year, end, _last_day(end_year, end)), "season")


def _year(y: int) -> FuzzyDate:
    return FuzzyDate(f"{y:04d}", *_year_span(y, y), "year")


def _decade(y: int) -> FuzzyDate:
    d = y - y % 10
    return FuzzyDate(f"{d // 10:03d}X", *_year_span(d, d + 9), "decade")


def _century(y: int) -> FuzzyDate:
    c = y - y % 100
    return FuzzyDate(f"{c // 100:02d}XX", *_year_span(c, c + 99), "century")


def _range(a: FuzzyDate, b: FuzzyDate) -> FuzzyDate:
    if b.date_max < a.date_min:
        a, b = b, a
    return FuzzyDate(f"{a.edtf}/{b.edtf}", a.date_min, b.date_max, "range")


def _approx(fd: FuzzyDate, mark: str = "~") -> FuzzyDate:
    """Mark a date approximate (~) or uncertain (?) and widen its bounds."""
    lo, hi = fd.date_min, fd.date_max
    if fd.precision in ("year", "month", "day", "season"):
        lo = date(lo.year - APPROX_YEARS, 1, 1)
        hi = date(hi.year + APPROX_YEARS, 12, 31)
    elif fd.precision == "decade":
        lo = date(lo.year - 5, 1, 1)
        hi = date(hi.year + 5, 12, 31)
    return FuzzyDate(fd.edtf + mark, lo, hi, fd.precision)


def _year4(s: str) -> int:
    y = int(s)
    if not 1000 <= y <= 2999:
        raise ValueError(s)
    return y


def _parse_edtf(s: str) -> FuzzyDate | None:
    """Parse the EDTF subset we emit."""
    if "/" in s:
        a, b = s.split("/", 1)
        pa, pb = _parse_edtf(a), _parse_edtf(b)
        return _range(pa, pb) if pa and pb else None
    mark = ""
    if s and s[-1] in "~?%":
        s, mark = s[:-1], s[-1]
    fd = None
    if m := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s):
        fd = _day(*map(int, m.groups()))
    elif m := re.fullmatch(r"(\d{4})-(2[1-4])", s):
        y, code = int(m[1]), int(m[2])
        fd = _season(y, SEASON_BY_CODE[code][0])
    elif m := re.fullmatch(r"(\d{4})-(\d{2})", s):
        fd = _month(int(m[1]), int(m[2]))
    elif m := re.fullmatch(r"\d{4}", s):
        fd = _year(_year4(s))
    elif m := re.fullmatch(r"(\d{3})X", s):
        fd = _decade(int(m[1]) * 10)
    elif m := re.fullmatch(r"(\d{2})XX", s):
        fd = _century(int(m[1]) * 100)
    if fd and mark:
        fd = _approx(fd, "~" if mark == "%" else mark)
    return fd


def _parse_single(s: str) -> FuzzyDate | None:
    """Parse one free-form date expression (no ranges)."""
    s = s.strip().lower().rstrip(".,")
    if not s:
        return None

    if (fd := _parse_edtf(s.upper())) is not None:
        return fd

    if m := re.fullmatch(rf"{APPROX_WORDS}\s*(.+)", s):
        inner = _parse_single(m[1])
        return _approx(inner) if inner else None
    if s.endswith("?"):
        inner = _parse_single(s[:-1])
        return _approx(inner, "?") if inner else None

    # early / mid / late 1920s
    if m := re.fullmatch(r"(early|mid|middle|late)[\s-]*(\d{3})0'?s", s):
        d = int(m[2]) * 10
        lo, hi = {"early": (0, 3), "mid": (4, 6), "middle": (4, 6), "late": (7, 9)}[m[1]]
        return _range(_year(d + lo), _year(d + hi))
    if m := re.fullmatch(r"(\d{2})00'?s", s):         # 1800s (read as century)
        return _century(int(m[1]) * 100)
    if m := re.fullmatch(r"(\d{3})0'?s", s):          # 1920s
        return _decade(int(m[1]) * 10)
    if m := re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th) century", s):
        return _century((int(m[1]) - 1) * 100)

    if m := re.fullmatch(r"(spring|summer|autumn|fall|winter),?\s+(?:of\s+)?(\d{4})", s):
        return _season(_year4(m[2]), m[1])
    if m := re.fullmatch(r"(?:xmas|christmas),?\s+(\d{4})", s):
        return _month(_year4(m[1]), 12)

    month_re = "|".join(sorted(MONTHS, key=len, reverse=True))
    # May 14, 1923 / May 14 1923
    if m := re.fullmatch(rf"({month_re})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})", s):
        return _day(_year4(m[3]), MONTHS[m[1]], int(m[2]))
    # 14 May 1923
    if m := re.fullmatch(rf"(\d{{1,2}})(?:st|nd|rd|th)?\s+({month_re})\.?,?\s+(\d{{4}})", s):
        return _day(_year4(m[3]), MONTHS[m[2]], int(m[1]))
    # May 1923
    if m := re.fullmatch(rf"({month_re})\.?,?\s+(\d{{4}})", s):
        return _month(_year4(m[2]), MONTHS[m[1]])
    # 5/14/1923 (US order, as written on most of these photos)
    if m := re.fullmatch(r"(\d{1,2})[/.](\d{1,2})[/.](\d{4})", s):
        return _day(_year4(m[3]), int(m[1]), int(m[2]))
    # 5/1923
    if m := re.fullmatch(r"(\d{1,2})[/.](\d{4})", s):
        return _month(_year4(m[2]), int(m[1]))
    # 1923/5/14 handled by EDTF if dashed; accept slashes too
    if m := re.fullmatch(r"(\d{4})[/.](\d{1,2})[/.](\d{1,2})", s):
        return _day(_year4(m[1]), int(m[2]), int(m[3]))
    return None


def parse(text: str) -> FuzzyDate | None:
    """Parse free-form or EDTF text. Returns None if it can't be understood."""
    if text is None:
        return None
    s = text.strip()
    try:
        if (fd := _parse_single(s)) is not None:
            return fd
        # Ranges: "1920-1925", "1920 to 1925", "between 1920 and 1925"
        s2 = re.sub(r"^between\s+", "", s.strip(), flags=re.I)
        parts = re.split(r"\s*(?:\bto\b|\band\b|–|—|\s-\s|(?<=\d)-(?=\d{4}\b))\s*", s2, flags=re.I)
        if len(parts) == 2:
            a, b = _parse_single(parts[0]), _parse_single(parts[1])
            if a and b:
                return _range(a, b)
    except (ValueError, KeyError):
        return None
    return None


def xmp_date(fd: "FuzzyDate") -> str:
    """Plain date for photoshop:DateCreated, which can't express 'circa' or ranges:
    as precise as the fuzzy date allows ('1975-05-01', '1975-05', or the earliest year)."""
    d = fd.date_min
    if fd.precision == "day":
        return d.isoformat()
    if fd.precision == "month":
        return f"{d.year:04d}-{d.month:02d}"
    return f"{d.year:04d}"


def describe(fd: FuzzyDate) -> str:
    """Human-readable form for the UI."""
    e = fd.edtf
    if "/" in e:
        a, b = (parse(x) for x in e.split("/", 1))
        return f"{describe(a)} – {describe(b)}" if a and b else e
    prefix = suffix = ""
    if e.endswith("~"):
        prefix, e = "c. ", e[:-1]
    elif e.endswith("?"):
        suffix, e = "?", e[:-1]
    base = _parse_edtf(e)
    if base is None:
        return fd.edtf
    d, p = base.date_min, base.precision
    if p == "day":
        text = f"{calendar.month_name[d.month]} {d.day}, {d.year}"
    elif p == "month":
        text = f"{calendar.month_name[d.month]} {d.year}"
    elif p == "season":
        text = f"{SEASON_BY_CODE[int(e[-2:])][0].title()} {d.year}"
    elif p in ("decade", "century"):
        text = f"{d.year}s"
    else:
        text = f"{d.year}"
    return prefix + text + suffix

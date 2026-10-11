from datetime import date

import pytest

from backend.dates import describe, parse


@pytest.mark.parametrize(
    "text, edtf, lo, hi, precision",
    [
        ("1923-05-14", "1923-05-14", date(1923, 5, 14), date(1923, 5, 14), "day"),
        ("May 14, 1923", "1923-05-14", date(1923, 5, 14), date(1923, 5, 14), "day"),
        ("14 May 1923", "1923-05-14", date(1923, 5, 14), date(1923, 5, 14), "day"),
        ("5/14/1923", "1923-05-14", date(1923, 5, 14), date(1923, 5, 14), "day"),
        ("May 1923", "1923-05", date(1923, 5, 1), date(1923, 5, 31), "month"),
        ("Feb 1924", "1924-02", date(1924, 2, 1), date(1924, 2, 29), "month"),
        ("1923", "1923", date(1923, 1, 1), date(1923, 12, 31), "year"),
        ("1920s", "192X", date(1920, 1, 1), date(1929, 12, 31), "decade"),
        ("192X", "192X", date(1920, 1, 1), date(1929, 12, 31), "decade"),
        ("1800s", "18XX", date(1800, 1, 1), date(1899, 12, 31), "century"),
        ("19th century", "18XX", date(1800, 1, 1), date(1899, 12, 31), "century"),
        ("c. 1925", "1925~", date(1923, 1, 1), date(1927, 12, 31), "year"),
        ("about 1925", "1925~", date(1923, 1, 1), date(1927, 12, 31), "year"),
        ("1925?", "1925?", date(1923, 1, 1), date(1927, 12, 31), "year"),
        ("summer 1948", "1948-22", date(1948, 6, 1), date(1948, 8, 31), "season"),
        ("winter 1948", "1948-24", date(1948, 12, 1), date(1949, 2, 28), "season"),
        ("Xmas 1931", "1931-12", date(1931, 12, 1), date(1931, 12, 31), "month"),
        ("1920-1925", "1920/1925", date(1920, 1, 1), date(1925, 12, 31), "range"),
        ("1920 to 1925", "1920/1925", date(1920, 1, 1), date(1925, 12, 31), "range"),
        ("between 1920 and 1925", "1920/1925", date(1920, 1, 1), date(1925, 12, 31), "range"),
        ("early 1920s", "1920/1923", date(1920, 1, 1), date(1923, 12, 31), "range"),
        ("late 1930s", "1937/1939", date(1937, 1, 1), date(1939, 12, 31), "range"),
        ("1920/1925", "1920/1925", date(1920, 1, 1), date(1925, 12, 31), "range"),
    ],
)
def test_parse(text, edtf, lo, hi, precision):
    fd = parse(text)
    assert fd is not None, text
    assert (fd.edtf, fd.date_min, fd.date_max, fd.precision) == (edtf, lo, hi, precision)


@pytest.mark.parametrize("text", ["", "sometime", "2/30/1923", "13/1923", "Grandma's house"])
def test_unparseable(text):
    assert parse(text) is None


@pytest.mark.parametrize(
    "edtf, text",
    [
        ("1923-05-14", "May 14, 1923"),
        ("192X", "1920s"),
        ("1925~", "c. 1925"),
        ("1948-22", "Summer 1948"),
        ("1920/1925", "1920 – 1925"),
    ],
)
def test_describe(edtf, text):
    assert describe(parse(edtf)) == text


@pytest.mark.parametrize("text", ["1923-05-14", "1923-05", "1923", "1920s", "1800s", "c. 1925",
                                  "1925?", "summer 1948", "winter 1948", "1920-1925",
                                  "early 1920s", "c. 1920s", "May 1923?"])
def test_describe_round_trips(text):
    """The UI shows describe() output and saves it back, so it must re-parse identically."""
    fd = parse(text)
    assert parse(describe(fd)) == fd

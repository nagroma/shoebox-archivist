"""Which of a person's names to show.

A person has a main name (`people.name`, which also anchors the keyword in the files) and
other names (`person_names`: kind birth | married | nickname | other, optional `from_year`).
The main name may carry its own `name_from_year` (e.g. a married name used from 1984, with
the birth name as an alias).

`pick` returns the name to show for a photo dated `year`, or the current name for year=None.
"""
from __future__ import annotations

FIELD, ROW = "\x1f", "\x1e"   # separators for the SQL group_concat of a person's aliases

Alias = tuple[str, str, int | None]   # name, kind, from_year

# SQL fragment: a person's aliases as one string, for `parse_aliases`. {pid} is a column expr.
ALIAS_BLOB_SQL = (
    "(SELECT group_concat(pn.name || char(31) || pn.kind || char(31) || COALESCE(pn.from_year, ''), "
    "char(30)) FROM person_names pn WHERE pn.person_id = {pid})"
)


def parse_aliases(blob: str | None) -> list[Alias]:
    out: list[Alias] = []
    for row in (blob or "").split(ROW):
        if not row:
            continue
        name, kind, year = row.split(FIELD)
        out.append((name, kind, int(year) if year else None))
    return out


def pick(primary: str, primary_from: int | None, aliases: list[Alias], year: int | None) -> str:
    dated: list[tuple[int, str]] = [(y, n) for n, _k, y in aliases if y is not None]
    if primary_from is not None:
        dated.append((primary_from, primary))
    birth = next((n for n, k, y in aliases if y is None and k == "birth"), None)
    rank = {"married": 0, "nickname": 1}
    undated = sorted((a for a in aliases if a[2] is None and a[1] != "birth"),
                     key=lambda a: rank.get(a[1], 2))
    current = undated[0][0] if undated else None

    if year is None:                      # no date: the name in use now
        if dated:
            return max(dated)[1]
        return current or primary
    ok = [d for d in dated if d[0] <= year]
    if ok:
        return max(ok)[1]
    if dated:                             # before the first dated name
        return birth or primary
    return current or primary


def birth_name(primary: str, aliases: list[Alias]) -> str:
    """The name a person started with: an alias of kind 'birth', else the main name."""
    return next((n for n, k, _y in aliases if k == "birth"), primary)

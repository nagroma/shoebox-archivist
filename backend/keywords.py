"""Keyword vocabulary and the (provisional) rules for what each category means.

These rules are best guesses from the collection's existing photos and Keywords.txt; they
are expected to change once the keyword structure is refined. Keep them here,
in one place, and see docs/KEYWORD_RULES.md.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from . import db

# Category -> kind for the standard top-level groups. Any other bracketed group in
# Keywords.txt ([Smith], [Parish], ...) is a family or community group of people.
# A person can appear in more than one group (e.g. AnnBrown in People and [Parish]).
CATEGORY_KIND = {
    "Attributes": "attribute",
    "Events": "event",
    "Families": "family",
    "People": "person",
    "Places": "place",
    "Scouts": "scouts",
    "Subjects": "subject",
    "Other Keywords": "other",
}
KINDS = ("person", "family", "event", "place", "subject", "scouts", "attribute", "other")

# Category for people named in this app who have no keyword yet.
DEFAULT_PERSON_CATEGORY = "People"

# Attribute tags with meaning for the date (everything else is just a grouping tag).
UNKNOWN_DATE = "unknowndate"
CONFIRMED_DATE = "confirmeddate"


def kind_of(category: str, conn: sqlite3.Connection | None = None) -> str:
    """Standard groups by name; otherwise whatever kind the group already has in the DB
    (set from Keywords.txt), else 'other'."""
    category = category.strip("[]")
    if category in CATEGORY_KIND:
        return CATEGORY_KIND[category]
    if conn is not None:
        row = conn.execute("SELECT kind FROM keywords WHERE category = ? "
                           "ORDER BY in_vocab DESC LIMIT 1", (category,)).fetchone()
        if row:
            return row["kind"]
    return "other"


def display_name(name: str) -> str:
    """'JohnSmith' -> 'John Smith', 'JoePBlack' -> 'Joe P Black'."""
    if " " in name:
        return name
    return re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", name)


def keyword_name(person_name: str) -> str:
    """'John Smith' -> 'JohnSmith' (the collection's keyword style)."""
    return "".join(w[:1].upper() + w[1:] for w in person_name.split())


def parse_vocabulary(text: str) -> list[tuple[str, str]]:
    """Parse a Lightroom keyword export (tab-indented; '[Group]' = container keyword)
    into (category, name) pairs. Only two levels are used in practice."""
    out, category = [], None
    for line in text.splitlines():
        if not line.strip():
            continue
        if not line[0].isspace():
            category = line.strip().strip("[]")
        elif category:
            out.append((category, line.strip()))
    return out


def person_groups(text: str) -> set[str]:
    """Bracketed top-level groups that aren't standard categories: families/communities."""
    return {line.strip().strip("[]") for line in text.splitlines()
            if line.strip().startswith("[") and not line[0].isspace()
            and line.strip().strip("[]") not in CATEGORY_KIND}


def split(keyword: str) -> tuple[str | None, str]:
    """'Smith|JohnSmith' -> ('Smith', 'JohnSmith'). Deeper paths keep the top level
    as category and the leaf as name."""
    parts = [p.strip() for p in keyword.split("|") if p.strip()]
    if len(parts) == 1:
        return None, parts[0]
    return parts[0].strip("[]"), parts[-1]


# ---------------------------------------------------------------- DB helpers

def ensure(conn: sqlite3.Connection, category: str, name: str, in_vocab: bool = False,
           kind: str | None = None) -> int:
    """Get or create a keyword; person keywords get a linked people row."""
    row = conn.execute("SELECT id, person_id FROM keywords WHERE category = ? AND name = ?",
                       (category, name)).fetchone()
    if row:
        if in_vocab:
            conn.execute("UPDATE keywords SET in_vocab = 1 WHERE id = ?", (row["id"],))
        return row["id"]
    kind = kind or kind_of(category, conn)
    person_id = None
    if kind == "person":
        # Same name in two groups = same person (until proven otherwise).
        other = conn.execute("SELECT person_id FROM keywords WHERE name = ? AND person_id "
                             "IS NOT NULL", (name,)).fetchone()
        person_id = other["person_id"] if other else db.get_or_create_person(conn, display_name(name))
    return conn.execute(
        "INSERT INTO keywords(category, name, kind, person_id, in_vocab) VALUES (?, ?, ?, ?, ?)",
        (category, name, kind, person_id, int(in_vocab))).lastrowid


def resolve(conn: sqlite3.Connection, keyword: str) -> int:
    """Keyword id for a file keyword. Flat keywords (no '|') are matched to an existing
    keyword by name, ignoring case and spaces ('Mary White' = 'MaryWhite'); unknown
    ones go to 'Other Keywords'."""
    category, name = split(keyword)
    if category is None:
        row = conn.execute("SELECT id FROM keywords WHERE lower(replace(name, ' ', '')) = ? "
                           "ORDER BY in_vocab DESC, id",
                           (name.replace(" ", "").lower(),)).fetchone()
        if row:
            return row["id"]
        category = "Other Keywords"
    return ensure(conn, category, name)


def load_vocabulary(conn: sqlite3.Connection, path: Path) -> int:
    text = path.read_text(encoding="utf-8-sig")
    pairs = parse_vocabulary(text)
    people = person_groups(text)
    for category, name in pairs:
        ensure(conn, category, name, in_vocab=True,
               kind="person" if category in people else None)
    conn.commit()
    return len(pairs)


def path_of(conn: sqlite3.Connection, keyword_id: int) -> str:
    r = conn.execute("SELECT category, name FROM keywords WHERE id = ?", (keyword_id,)).fetchone()
    return f"{r['category']}|{r['name']}"


def person_keyword(conn: sqlite3.Connection, person_id: int) -> int:
    """The keyword written to files for a person; created if they don't have one."""
    row = conn.execute("SELECT id FROM keywords WHERE person_id = ? ORDER BY in_vocab DESC, id",
                       (person_id,)).fetchone()
    if row:
        return row["id"]
    name = conn.execute("SELECT name FROM people WHERE id = ?", (person_id,)).fetchone()["name"]
    return conn.execute(
        "INSERT INTO keywords(category, name, kind, person_id) VALUES (?, ?, 'person', ?)",
        (DEFAULT_PERSON_CATEGORY, keyword_name(name), person_id)).lastrowid


def photo_people(conn: sqlite3.Connection, photo_id: int) -> set[int]:
    """People the photo's keywords say are in it."""
    return {r[0] for r in conn.execute(
        "SELECT k.person_id FROM photo_keywords pk JOIN keywords k ON k.id = pk.keyword_id "
        "WHERE pk.photo_id = ? AND k.person_id IS NOT NULL", (photo_id,))}


def date_rule(date_created: str | None, tags: set[str]) -> str | None:
    """EDTF date for a file's photoshop:DateCreated, given its keyword names.

    The scans carry placeholder dates (a whole batch on 1975-05-01) tagged
    'unknowndate', so those become 'circa year'. Everything else is taken as given.
    """
    if not date_created:
        return None
    m = re.match(r"(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?", date_created)
    if not m:
        return None
    y, mo, d = m.groups()
    if UNKNOWN_DATE in tags:
        return f"{y}~"
    return "-".join(x for x in (y, mo, d) if x)

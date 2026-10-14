"""Keyword vocabulary and the rules for what each category means.

A library chooses its own top-level *facets* (People, Places, ...; see FACET_KINDS), stored
in its database. Libraries created before facets existed fall back to LEGACY_CATEGORY_KIND.
See docs/KEYWORD_RULES.md.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from . import db

# What a facet's keywords mean to the app. Only 'person' changes behaviour (a keyword
# there is a person: linked to faces, named from CamelCase).
FACET_KINDS = ("person", "event", "place", "subject", "attribute", "other")
# Older libraries also have these two, from their Keywords.txt.
KINDS = FACET_KINDS + ("family", "scouts")

# Used only when a library has no facets configured (libraries from before facets existed).
# Any other bracketed group in Keywords.txt ([Smith], [Parish], ...) is a group of people.
LEGACY_CATEGORY_KIND = {
    "Attributes": "attribute",
    "Events": "event",
    "Families": "family",
    "People": "person",
    "Places": "place",
    "Scouts": "scouts",
    "Subjects": "subject",
    "Other Keywords": "other",
}
CATEGORY_KIND = LEGACY_CATEGORY_KIND

# Category for people named in this app when the library has no person facet.
DEFAULT_PERSON_CATEGORY = "People"
FACETS_SETTING = "facets"
OTHER_CATEGORY = "Other Keywords"

# Attribute tags with meaning for the date (everything else is just a grouping tag).
UNKNOWN_DATE = "unknowndate"
CONFIRMED_DATE = "confirmeddate"

_KIND_GUESS = {
    "person": {"people", "person", "persons", "family", "names", "who"},
    "place": {"places", "place", "locations", "location", "where"},
    "event": {"events", "event", "occasions", "when"},
    "subject": {"subjects", "subject", "things", "topics", "what"},
    "attribute": {"attributes", "format", "curation", "rating", "ratings", "labels", "status"},
}


def guess_kind(facet_name: str) -> str:
    """Best guess at what a top-level keyword found in files means, from its name."""
    low = facet_name.strip("[] ").lower()
    return next((k for k, names in _KIND_GUESS.items() if low in names), "other")


def top_level(category: str) -> str:
    return category.split("|", 1)[0].strip().strip("[]")


def get_facets(conn: sqlite3.Connection) -> list[dict]:
    """The library's top-level keyword groups: [{'name', 'kind'}]. Empty = not configured."""
    try:
        data = json.loads(db.get_setting(conn, FACETS_SETTING) or "[]")
    except ValueError:
        return []
    return [f for f in data if isinstance(f, dict) and f.get("name")]


def set_facets(conn: sqlite3.Connection, facets: list[dict]) -> list[dict]:
    """Replace the facet list. Raises ValueError for bad names/kinds, or for removing a
    facet that has keywords or changing a facet to/from 'person' once it has keywords."""
    clean, seen = [], set()
    for f in facets:
        name, kind = str(f.get("name", "")).strip().strip("[]").strip(), f.get("kind", "other")
        if not name or "|" in name:
            raise ValueError("A facet needs a name without '|'")
        if kind not in FACET_KINDS:
            raise ValueError(f"Unknown kind {kind!r} for {name}")
        if name.lower() in seen:
            raise ValueError(f"Facet {name!r} is listed twice")
        seen.add(name.lower())
        clean.append({"name": name, "kind": kind})
    old = {f["name"]: f["kind"] for f in get_facets(conn)}
    new = {f["name"]: f["kind"] for f in clean}
    for name in old.keys() - new.keys():
        if _facet_keyword_count(conn, name):
            raise ValueError(f"Facet {name!r} still has keywords; remove them first")
    for name, kind in new.items():
        if name in old and old[name] != kind:
            if "person" in (old[name], kind) and _facet_keyword_count(conn, name):
                raise ValueError(f"{name!r} has keywords, so it can't change to or from 'person'")
            conn.execute("UPDATE keywords SET kind = ? WHERE category = ? OR category LIKE ?",
                         (kind, name, name + "|%"))
    db.set_setting(conn, FACETS_SETTING, json.dumps(clean))
    conn.commit()
    return clean


def _facet_keyword_count(conn: sqlite3.Connection, name: str) -> int:
    return conn.execute("SELECT COUNT(*) FROM keywords WHERE category = ? OR category LIKE ?",
                        (name, name + "|%")).fetchone()[0]


def default_person_category(conn: sqlite3.Connection) -> str:
    """Where a new person's keyword goes. With several person facets (Ashdown, Marlowe, People...)
    the generic one (`People`) wins, so nobody is filed under a family they were not in."""
    people = [f["name"] for f in get_facets(conn) if f["kind"] == "person"]
    return next((n for n in people if n.lower() == DEFAULT_PERSON_CATEGORY.lower()),
                people[0] if people else DEFAULT_PERSON_CATEGORY)


NAME_SHAPE = re.compile(r"^[A-Z][a-z]+(?:[A-Z][a-z]+)+$")   # JuliaAshdown, NoahWren
DISMISSED_SETTING = "dismissed_groups"


def group_hint(leaves: dict[str, int]) -> dict:
    """Most-used leaf keywords of a group and whether they look like people's names.
    A hint only; the person picks the kind."""
    names = sorted(leaves, key=lambda n: (-leaves[n], n))
    shaped = sum(bool(NAME_SHAPE.match(n)) for n in names)
    return {"samples": names[:5], "keywords": len(names),
            "looks_like_people": len(names) >= 5 and shaped / len(names) >= 0.7}


def unmapped_groups(conn: sqlite3.Connection) -> list[dict]:
    """Top-level keyword groups in the library that match no facet (photos added later brought
    them) and were not left alone on purpose. Libraries with no facets report nothing."""
    facets = {f["name"].lower() for f in get_facets(conn)}
    if not facets:
        return []
    try:
        dismissed = {n.lower() for n in json.loads(db.get_setting(conn, DISMISSED_SETTING) or "[]")}
    except ValueError:
        dismissed = set()
    groups: dict[str, dict] = {}
    for r in conn.execute("SELECT k.category, k.name, COUNT(pk.photo_id) AS n FROM keywords k "
                          "LEFT JOIN photo_keywords pk ON pk.keyword_id = k.id GROUP BY k.id"):
        top = top_level(r["category"])
        if top.lower() in facets | dismissed or top == OTHER_CATEGORY:
            continue
        g = groups.setdefault(top, {"name": top, "photos": 0, "_leaves": {}})
        g["photos"] += r["n"]
        g["_leaves"][r["name"]] = r["n"]
    out = []
    for g in groups.values():
        leaves = g.pop("_leaves")
        out.append({**g, **group_hint(leaves), "kind": guess_kind(g["name"])})
    return sorted(out, key=lambda g: g["name"].lower())


def adopt_group(conn: sqlite3.Connection, name: str, kind: str) -> list[dict]:
    """Add an unmapped group as a facet of the given kind. File keywords are not touched;
    person groups get their people rows so they can be matched to faces."""
    facets = get_facets(conn)
    if any(f["name"].lower() == name.lower() for f in facets):
        raise ValueError(f"{name!r} is already a facet")
    real = conn.execute("SELECT category FROM keywords WHERE lower(category) = lower(?) "
                        "OR lower(category) LIKE lower(?) LIMIT 1", (name, name + "|%")).fetchone()
    if not real:
        raise ValueError(f"No keywords in a group called {name!r}")
    name = top_level(real["category"])
    out = set_facets(conn, facets + [{"name": name, "kind": kind}])
    conn.execute("UPDATE keywords SET kind = ? WHERE category = ? OR category LIKE ?",
                 (kind, name, name + "|%"))
    if kind == "person":
        for r in conn.execute("SELECT id, name FROM keywords WHERE person_id IS NULL AND "
                              "(category = ? OR category LIKE ?)", (name, name + "|%")).fetchall():
            other = conn.execute("SELECT person_id FROM keywords WHERE name = ? AND person_id "
                                 "IS NOT NULL", (r["name"],)).fetchone()
            pid = other["person_id"] if other else db.get_or_create_person(conn, display_name(r["name"]))
            conn.execute("UPDATE keywords SET person_id = ? WHERE id = ?", (pid, r["id"]))
    conn.commit()
    return out


def dismiss_group(conn: sqlite3.Connection, name: str) -> None:
    """Leave a group as it is: it stays in the files and the database, and is not offered again."""
    try:
        left = json.loads(db.get_setting(conn, DISMISSED_SETTING) or "[]")
    except ValueError:
        left = []
    if name.lower() not in {n.lower() for n in left}:
        db.set_setting(conn, DISMISSED_SETTING, json.dumps([*left, name]))
        conn.commit()


def family_category(conn: sqlite3.Connection) -> str:
    """Where family/branch keywords go: the library's own `Family` or `Families` group if it
    has one (the owner's files have `Families|EastwickFamily`), else `Family`. Never a second group."""
    names = {f["name"].lower(): f["name"] for f in get_facets(conn)}
    for n in ("family", "families"):
        if n in names:
            return names[n]
    return "Family"


def kind_of(category: str, conn: sqlite3.Connection | None = None) -> str:
    """What a category means. Library facets first; a library without facets uses the
    legacy standard groups; otherwise whatever kind the group already has in the DB
    (set from Keywords.txt), else 'other'. Deeper paths use their top level."""
    top = top_level(category)
    facets = get_facets(conn) if conn is not None else []
    if facets:
        for f in facets:
            if f["name"].lower() == top.lower():
                return f["kind"]
    elif top in LEGACY_CATEGORY_KIND:
        return LEGACY_CATEGORY_KIND[top]
    if conn is not None:
        row = conn.execute("SELECT kind FROM keywords WHERE category = ? OR category LIKE ? "
                           "ORDER BY in_vocab DESC LIMIT 1", (top, top + "|%")).fetchone()
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
    """Parse a Lightroom/Bridge keyword export (tab-indented; '[Group]' = container
    keyword) into (category, name) pairs, where category is the parent path
    ('Places|USA', 'Smith'). Top-level lines are categories, not keywords."""
    out: list[tuple[str, str]] = []
    stack: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        depth = len(line) - len(line.lstrip("\t "))
        name = line.strip().strip("[]").strip()
        if not name:
            continue
        del stack[depth:]
        if stack:
            out.append(("|".join(stack), name))
        stack.append(name)
    return out


def export_vocabulary(conn: sqlite3.Connection) -> str:
    """The library's keywords as a Keywords.txt (tab-indented), for import into Bridge or
    Lightroom. Facets are listed even when empty."""
    tree: dict = {}
    for f in get_facets(conn):
        tree.setdefault(f["name"], {})
    for r in conn.execute("SELECT category, name FROM keywords ORDER BY category, name"):
        node = tree
        for part in [*r["category"].split("|"), r["name"]]:
            node = node.setdefault(part.strip("[]"), {})
    lines: list[str] = []

    def walk(node: dict, depth: int) -> None:
        for name in sorted(node, key=str.lower):
            lines.append("\t" * depth + name)
            walk(node[name], depth + 1)
    walk(tree, 0)
    return "\n".join(lines) + "\n"


def person_groups(text: str) -> set[str]:
    """Bracketed top-level groups that aren't standard categories: families/communities."""
    return {line.strip().strip("[]") for line in text.splitlines()
            if line.strip().startswith("[") and not line[0].isspace()
            and line.strip().strip("[]") not in LEGACY_CATEGORY_KIND}


def split(keyword: str) -> tuple[str | None, str]:
    """'Smith|JohnSmith' -> ('Smith', 'JohnSmith'); 'Places|USA|Texas' -> ('Places|USA',
    'Texas'). The category is the whole parent path, so the keyword can be written back
    to the file unchanged."""
    parts = [p.strip().strip("[]").strip() for p in keyword.split("|") if p.strip()]
    if len(parts) == 1:
        return None, parts[0]
    return "|".join(parts[:-1]), parts[-1]


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
        category = OTHER_CATEGORY
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
    # The same name may already exist as a keyword in the files (`Ashdown|JuliaAshdown`) that no
    # person owns yet: reuse it rather than inventing `People|JuliaAshdown` beside it.
    row = conn.execute(
        "SELECT k.id FROM keywords k LEFT JOIN photo_keywords pk ON pk.keyword_id = k.id "
        "WHERE lower(k.name) = lower(?) AND k.person_id IS NULL AND k.kind = 'person' "
        "GROUP BY k.id ORDER BY COUNT(pk.photo_id) DESC, k.id LIMIT 1", (keyword_name(name),)).fetchone()
    if row:
        conn.execute("UPDATE keywords SET person_id = ? WHERE id = ?", (person_id, row["id"]))
        return row["id"]
    return conn.execute(
        "INSERT INTO keywords(category, name, kind, person_id) VALUES (?, ?, 'person', ?)",
        (default_person_category(conn), keyword_name(name), person_id)).lastrowid


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

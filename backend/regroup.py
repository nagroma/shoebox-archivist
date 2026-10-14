"""Convert family-name groups into People + Family keywords, only on explicit confirmation.

Collections keyworded in Bridge often hold people as `<FamilyName>|<PersonName>`
(`Ashdown|JuliaAshdown`). The app's model keeps people under a person facet and family
names under `Family`. Converting one keyword gives two:

    Ashdown|JuliaAshdown  ->  People|JuliaAshdown  +  Family|Ashdown

`plan` changes nothing and says what would happen; `apply` does it. The old keyword is
removed from the file with provenance (sa:RemovedKeywords; `pm strip` puts it back) and the
new ones are listed in sa:AddedKeywords. Nothing here runs without a caller asking for it.

This is a migration *option*: the owner's own structure keeps people under `Ashdown|` / `Marlowe|` /
`AshdownMarlowe|` and uses `People` only for people outside those families (docs/KEYWORD_STRATEGY.md).
The app must work without running it.
"""
from __future__ import annotations

import sqlite3

from . import actions, db, keywords

FAMILY_CATEGORY = "Family"


def _groups_keywords(conn: sqlite3.Connection, group: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT k.id, k.name, COUNT(pk.photo_id) AS photos FROM keywords k "
        "LEFT JOIN photo_keywords pk ON pk.keyword_id = k.id "
        "WHERE lower(k.category) = lower(?) GROUP BY k.id ORDER BY k.name", (group,)).fetchall()


def _existing(conn: sqlite3.Connection, category: str, name: str) -> int | None:
    row = conn.execute("SELECT id FROM keywords WHERE category = ? AND name = ?",
                       (category, name)).fetchone()
    return row["id"] if row else None


def plan(conn: sqlite3.Connection, groups: list[str], people_category: str | None = None) -> dict:
    """What converting these groups would do. Nothing is changed."""
    people_cat = people_category or keywords.default_person_category(conn)
    fam_cat = keywords.family_category(conn)
    out_groups, photos = [], set()
    for g in groups:
        real = conn.execute("SELECT category FROM keywords WHERE lower(category) = lower(?) LIMIT 1",
                            (g,)).fetchone()
        name = real["category"] if real else g
        kws = _groups_keywords(conn, name)
        people = []
        for k in kws:
            target = _existing(conn, people_cat, k["name"])
            people.append({"keyword_id": k["id"], "name": k["name"],
                           "display": keywords.display_name(k["name"]),
                           "photos": k["photos"], "to": f"{people_cat}|{k['name']}",
                           "merges_existing": target is not None})
            photos.update(r[0] for r in conn.execute(
                "SELECT photo_id FROM photo_keywords WHERE keyword_id = ?", (k["id"],)))
        deeper = conn.execute("SELECT COUNT(*) FROM keywords WHERE lower(category) LIKE lower(?)",
                              (name + "|%",)).fetchone()[0]
        out_groups.append({"group": name, "family_keyword": f"{fam_cat}|{name}",
                           "people": people, "skipped_deeper": deeper})
    return {"people_category": people_cat, "family_category": fam_cat,
            "groups": out_groups, "photos": len(photos),
            "keywords": sum(len(g["people"]) for g in out_groups), "applied": False}


def apply(conn: sqlite3.Connection, groups: list[str], people_category: str | None = None) -> dict:
    """Do what `plan` describes: for each photo with `Group|Name`, add `People|Name` and
    `Family|Group`, then remove `Group|Name`. Facets are added when missing."""
    p = plan(conn, groups, people_category)
    people_cat, fam_cat = p["people_category"], p["family_category"]
    facets = keywords.get_facets(conn)
    names = {f["name"].lower() for f in facets}
    extra = [{"name": n, "kind": k} for n, k in ((people_cat, "person"), (fam_cat, "other"))
             if n.lower() not in names]
    if extra:
        keywords.set_facets(conn, facets + extra)

    converted = failed = 0
    for g in p["groups"]:
        if not g["people"]:
            continue
        fam_id = keywords.ensure(conn, fam_cat, g["group"])
        for person in g["people"]:
            new_id = keywords.ensure(conn, people_cat, person["name"], in_vocab=True)
            old_id = person["keyword_id"]
            photo_ids = [r[0] for r in conn.execute(
                "SELECT photo_id FROM photo_keywords WHERE keyword_id = ?", (old_id,))]
            for ph in photo_ids:
                ok = actions.add_photo_keyword(conn, ph, new_id) or _has(conn, ph, new_id)
                ok = ok and (actions.add_photo_keyword(conn, ph, fam_id) or _has(conn, ph, fam_id))
                if ok and actions.remove_photo_keyword(conn, ph, old_id, only_app=False):
                    converted += 1
                else:
                    failed += 1
            conn.commit()
            if not conn.execute("SELECT 1 FROM photo_keywords WHERE keyword_id = ?",
                                (old_id,)).fetchone():
                conn.execute("DELETE FROM keywords WHERE id = ?", (old_id,))
        conn.commit()
        left = conn.execute("SELECT 1 FROM keywords WHERE lower(category) = lower(?) "
                            "OR lower(category) LIKE lower(?) LIMIT 1",
                            (g["group"], g["group"] + "|%")).fetchone()
        if not left:   # the old group is empty: drop its facet
            keep = [f for f in keywords.get_facets(conn) if f["name"].lower() != g["group"].lower()]
            keywords.set_facets(conn, keep)
    actions.resuggest(conn)
    return {**p, "applied": True, "converted": converted, "failed": failed}


def _has(conn: sqlite3.Connection, photo_id: int, keyword_id: int) -> bool:
    return conn.execute("SELECT 1 FROM photo_keywords WHERE photo_id = ? AND keyword_id = ?",
                        (photo_id, keyword_id)).fetchone() is not None

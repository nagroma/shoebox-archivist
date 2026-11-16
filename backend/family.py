"""Family links and the labels derived from them.

Only two kinds of fact are stored (`relations`): "a is a parent of b" and "a and b are
partners" (a partnership can be marked ended: a former partner). Siblings, grandparents, cousins, ... are derived, and labelled from the library's
curator (the "home person"). No gender is recorded, so labels
name both, as 'Aunt/Uncle' always did: Mother/Father, Brother/Sister, Son/Daughter.
"""
from __future__ import annotations

import sqlite3

KINDS = ("parent", "partner")


def _graph(conn: sqlite3.Connection):
    parents: dict[int, set[int]] = {}
    children: dict[int, set[int]] = {}
    partners: dict[int, set[int]] = {}
    for r in conn.execute("SELECT a, b, kind FROM relations"):
        if r["kind"] == "parent":
            parents.setdefault(r["b"], set()).add(r["a"])
            children.setdefault(r["a"], set()).add(r["b"])
        else:
            partners.setdefault(r["a"], set()).add(r["b"])
            partners.setdefault(r["b"], set()).add(r["a"])
    return parents, children, partners


def _former(conn: sqlite3.Connection) -> set[tuple[int, int]]:
    """Partner links that have ended, as (a, b) with a < b."""
    return {(r["a"], r["b"]) for r in conn.execute(
        "SELECT a, b FROM relations WHERE kind = 'partner' AND ended = 1")}


def _current(partners: dict[int, set[int]], former: set[tuple[int, int]],
             p: int) -> set[int]:
    return {q for q in partners.get(p, ()) if (min(p, q), max(p, q)) not in former}


def _up(start: int, parents: dict[int, set[int]]) -> dict[int, int]:
    """Ancestors of `start` with their distance in generations (nearest path)."""
    seen: dict[int, int] = {}
    frontier, depth = {start}, 0
    while frontier:
        depth += 1
        nxt: set[int] = set()
        for p in frontier:
            for q in parents.get(p, ()):
                if q not in seen:
                    seen[q] = depth
                    nxt.add(q)
        frontier = nxt
    return seen


def _great(n: int, word: str) -> str:
    """'Aunt/Uncle' -> 'Great-aunt/great-uncle' (n generations further out)."""
    if n <= 0:
        return word
    text = "/".join("great-" * n + w.lower() for w in word.split("/"))
    return text[0].upper() + text[1:]


def _ordinal(n: int) -> str:
    return {1: "1st", 2: "2nd", 3: "3rd"}.get(n, f"{n}th")


def _blood_label(x: int, home: int, parents) -> str | None:
    """How x is related to home through parent links only."""
    if x == home:
        return "You"
    up_x, up_h = _up(x, parents), _up(home, parents)
    if x in up_h:
        d = up_h[x]
        return "Mother/Father" if d == 1 else _great(d - 2, "Grandmother/Grandfather")
    if home in up_x:
        d = up_x[home]
        return "Son/Daughter" if d == 1 else _great(d - 2, "Grandson/Granddaughter")
    best: tuple[int, int] | None = None
    for anc, dx in up_x.items():
        dh = up_h.get(anc)
        if dh is not None and (best is None or dx + dh < sum(best)):
            best = (dx, dh)
    if best is None:
        return None
    dx, dh = best
    if dx == 1 and dh == 1:
        return "Brother/Sister"
    if dx == 1:   # a child of one of home's ancestors
        return _great(dh - 2, "Aunt/Uncle")
    if dh == 1:
        return _great(dx - 2, "Niece/Nephew")
    k = min(dx, dh) - 1
    gap = abs(dx - dh)
    s = f"{_ordinal(k)} cousin"
    return s if gap == 0 else f"{s}, {gap}x removed"


def labels(conn: sqlite3.Connection, home: int | None) -> dict[int, str]:
    """Relationship of every connected person to `home` ('Mother/Father', 'Partner', ...)."""
    if home is None:
        return {}
    parents, _, partners = _graph(conn)
    former = _former(conn)
    people = {r[0] for r in conn.execute("SELECT id FROM people")}
    out: dict[int, str] = {}
    for pid in people:
        lab = _blood_label(pid, home, parents)
        if lab:
            out[pid] = lab
    for pid in people - set(out):
        if pid in partners.get(home, ()):
            out[pid] = ("Former partner" if (min(pid, home), max(pid, home)) in former
                        else "Partner")
    for pid in people - set(out):  # partner of a relative, or relative of the partner
        for q in partners.get(pid, ()):
            if q in out and q != home:
                kind = "Former partner" if (min(pid, q), max(pid, q)) in former else "Partner"
                out[pid] = f"{kind} of {out[q].lower()}"
                break
        else:
            for h in _current(partners, former, home):
                lab = _blood_label(pid, h, parents)
                if lab and lab != "You":
                    out[pid] = f"Partner's {lab.lower()}"
                    break
    return out


def relatives(conn: sqlite3.Connection, pid: int) -> dict[str, list[int]]:
    parents, children, partners = _graph(conn)
    mine = parents.get(pid, set())
    sibs = {c for p in mine for c in children.get(p, ())} - {pid}
    current = _current(partners, _former(conn), pid)
    return {"parents": sorted(mine), "partners": sorted(current),
            "former_partners": sorted(partners.get(pid, set()) - current),
            "children": sorted(children.get(pid, ())), "siblings": sorted(sibs)}


def end_years(conn: sqlite3.Connection, pid: int) -> dict[int, int | None]:
    """Former partners of `pid` -> year the partnership ended (None if unknown)."""
    out: dict[int, int | None] = {}
    for r in conn.execute("SELECT a, b, end_year FROM relations WHERE kind = 'partner' "
                          "AND ended = 1 AND (a = ? OR b = ?)", (pid, pid)):
        out[r["b"] if r["a"] == pid else r["a"]] = r["end_year"]
    return out


def surname(name: str) -> str:
    parts = name.split()
    return parts[-1] if len(parts) > 1 else name.strip()


def branches(conn: sqlite3.Connection) -> dict[int, set[str]]:
    """Family branches per person. A branch is the descendants of a 'root' (someone with no
    recorded parents who has children or a partner), named after the root's birth surname.
    A person gets a branch for every root they descend from. Someone who is related to the
    curator by blood also gets the branches of a current partner who is not (married in):
    Jennifer gets her husband's Driver; the husband gets nothing of hers. A former partner's
    branches are not shared."""
    from . import db, names
    parents, children, partners = _graph(conn)
    former = _former(conn)
    aliases: dict[int, list[names.Alias]] = {}
    for r in conn.execute("SELECT person_id, name, kind, from_year FROM person_names"):
        aliases.setdefault(r["person_id"], []).append((r["name"], r["kind"], r["from_year"]))
    label = {r["id"]: names.birth_name(r["name"], aliases.get(r["id"], []))
             for r in conn.execute("SELECT id, name FROM people")}
    roots = {p for p in label if not parents.get(p) and (children.get(p) or partners.get(p))}
    own: dict[int, set[str]] = {}
    for p in label:
        mine = ({p} | set(_up(p, parents))) & roots
        if mine:
            own[p] = {surname(label[r]) for r in mine}

    raw = db.get_setting(conn, "curator_person_id")
    home = int(raw) if raw and raw.isdigit() else None
    out = {p: set(bs) for p, bs in own.items()}
    if home is not None:
        blood = {p for p in label if p == home or _blood_label(p, home, parents)}
        for p in blood:
            for q in _current(partners, former, p):
                if q not in blood:
                    out.setdefault(p, set()).update(own.get(q, ()))
    return out


def circle(conn: sqlite3.Connection, pid: int, generations: int = 1) -> dict[int, int]:
    """The people in `pid`'s family with their generation relative to `pid` (parents -1,
    children +1): ancestors and descendants up to `generations` away, their partners, and
    `pid`'s siblings (other children of their parents)."""
    parents, children, partners = _graph(conn)
    gen: dict[int, int] = {pid: 0}
    for anc, d in _up(pid, parents).items():
        if d <= generations:
            gen[anc] = -d
    frontier = {pid}
    for d in range(1, generations + 1):
        frontier = {c for p in frontier for c in children.get(p, ())} - set(gen)
        for c in frontier:
            gen[c] = d
    for p in parents.get(pid, ()):
        for sib in children.get(p, ()):
            gen.setdefault(sib, 0)
    for p, g in list(gen.items()):
        for q in partners.get(p, ()):
            gen.setdefault(q, g)
    return gen


def edges_among(conn: sqlite3.Connection, ids: set[int]) -> list[dict]:
    return [{"a": r["a"], "b": r["b"], "kind": r["kind"], "ended": bool(r["ended"])}
            for r in conn.execute("SELECT a, b, kind, ended FROM relations")
            if r["a"] in ids and r["b"] in ids]


def add(conn: sqlite3.Connection, kind: str, a: int, b: int) -> None:
    """kind 'parent': a is a parent of b. Raises ValueError if it makes no sense."""
    if kind not in KINDS:
        raise ValueError(f"unknown relation {kind!r}")
    if a == b:
        raise ValueError("A person can't be related to themself")
    if kind == "parent":
        parents, _, _ = _graph(conn)
        if b in _up(a, parents):
            raise ValueError("That would make someone their own ancestor")
    else:
        a, b = min(a, b), max(a, b)
    conn.execute("INSERT OR IGNORE INTO relations(a, b, kind) VALUES (?, ?, ?)", (a, b, kind))


def remove(conn: sqlite3.Connection, kind: str, a: int, b: int) -> None:
    if kind == "partner":
        a, b = min(a, b), max(a, b)
    conn.execute("DELETE FROM relations WHERE kind = ? AND a = ? AND b = ?", (kind, a, b))


def set_ended(conn: sqlite3.Connection, a: int, b: int, ended: bool,
              end_year: int | None = None) -> None:
    """Mark a partnership as over (optionally with the year) or current again."""
    a, b = min(a, b), max(a, b)
    cur = conn.execute("UPDATE relations SET ended = ?, end_year = ? WHERE kind = 'partner' "
                       "AND a = ? AND b = ?", (int(ended), end_year if ended else None, a, b))
    if cur.rowcount == 0:
        raise ValueError("They are not recorded as partners")


def move(conn: sqlite3.Connection, src: int, dst: int) -> None:
    """Merging people: links of src become links of dst (dropping any that would be invalid)."""
    for r in conn.execute("SELECT a, b, kind, ended, end_year FROM relations "
                          "WHERE a = ? OR b = ?", (src, src)).fetchall():
        a = dst if r["a"] == src else r["a"]
        b = dst if r["b"] == src else r["b"]
        conn.execute("DELETE FROM relations WHERE a = ? AND b = ? AND kind = ?", (r["a"], r["b"], r["kind"]))
        try:
            add(conn, r["kind"], a, b)
            if r["ended"]:
                set_ended(conn, a, b, True, r["end_year"])
        except ValueError:
            pass

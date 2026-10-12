"""Local web API + static UI.  Run with `uv run pm serve`."""
from __future__ import annotations

import os
import shutil
import sqlite3
import threading
from collections.abc import Iterator
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps
from pydantic import BaseModel

from . import (actions, candidates, cluster, config, dates, db, faces, family, ingest,
               keywords, library, match, names, xmp)

FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "dist"
SIZES = {"thumb": 320, "large": 2000}

app = FastAPI(title="Shoebox Archivist")


def _need_library() -> Path:
    path = library.db_path()
    if path is None:
        raise HTTPException(409, "no_library")
    return path


def get_conn() -> Iterator[sqlite3.Connection]:
    conn = db.connect(_need_library())
    try:
        yield conn
    finally:
        conn.close()


Conn = Depends(get_conn)

FACE_SQL = """
SELECT f.id, f.image_id, i.photo_id, i.path, f.x1, f.y1, f.x2, f.y2, f.det_score,
       f.status, f.person_id,
       p.name AS primary_name, p.name_from_year,
       CAST(substr(ph.date_min, 1, 4) AS INTEGER) AS photo_year,
       """ + names.ALIAS_BLOB_SQL.format(pid="f.person_id") + """ AS alias_blob,
       f.confidence, f.cluster_id, f.label_source
FROM faces f JOIN images i ON i.id = f.image_id JOIN photos ph ON ph.id = i.photo_id
LEFT JOIN people p ON p.id = f.person_id
"""


def _name_on_photo(r: sqlite3.Row) -> str | None:
    """The person's name as it fits the photo's date (see names.pick)."""
    if r["primary_name"] is None:
        return None
    return names.pick(r["primary_name"], r["name_from_year"], names.parse_aliases(r["alias_blob"]),
                      r["photo_year"])


def _current_names(conn: sqlite3.Connection) -> dict[int, str]:
    """Every person's name in use now."""
    al = _aliases(conn)
    return {r["id"]: names.pick(r["name"], r["name_from_year"],
                                [(a["name"], a["kind"], a["from_year"]) for a in al.get(r["id"], [])], None)
            for r in conn.execute("SELECT id, name, name_from_year FROM people")}


def face_json(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"], "image_id": r["image_id"], "photo_id": r["photo_id"], "path": r["path"],
        "bbox": [r["x1"], r["y1"], r["x2"], r["y2"]], "det_score": r["det_score"],
        "status": r["status"], "person_id": r["person_id"], "person_name": _name_on_photo(r),
        "confidence": r["confidence"], "cluster_id": r["cluster_id"],
        "label_source": r["label_source"],
    }


def date_json(text: str | None) -> dict | None:
    fd = dates.parse(text) if text else None
    if fd is None:
        return None
    return {"edtf": fd.edtf, "display": str(fd), "min": fd.date_min.isoformat(),
            "max": fd.date_max.isoformat(), "precision": fd.precision}


# ---------------------------------------------------------------- overview

@app.get("/api/stats")
def stats(conn=Conn):
    q = lambda sql: conn.execute(sql).fetchone()[0]
    by_status = {r[0]: r[1] for r in conn.execute("SELECT status, COUNT(*) FROM faces GROUP BY status")}
    return {
        "library_root": db.get_setting(conn, "library_root"),
        "db_token": db.get_setting(conn, "db_token"),
        "photos": q("SELECT COUNT(*) FROM photos"),
        "people": q("SELECT COUNT(*) FROM people"),
        "faces": by_status,
        "candidates": q("SELECT COUNT(*) FROM faces WHERE candidate = 1 AND status != 'ignored'"),
        "clusters": q("SELECT COUNT(DISTINCT cluster_id) FROM faces WHERE cluster_id >= 0 "
                      "AND status IN ('unknown', 'suggested')"),
        "undated": q("SELECT COUNT(*) FROM photos WHERE date_text IS NULL"),
    }


# ---------------------------------------------------------------- clusters

@app.get("/api/clusters")
def clusters(conn=Conn):
    rows = conn.execute(FACE_SQL + " WHERE f.status IN ('unknown', 'suggested') "
                        "AND f.cluster_id IS NOT NULL ORDER BY f.cluster_id, f.id").fetchall()
    groups: dict[int, list] = {}
    for r in rows:
        groups.setdefault(r["cluster_id"], []).append(face_json(r))
    out = [{"cluster_id": cid, "faces": fs} for cid, fs in groups.items() if cid >= 0]
    out.sort(key=lambda c: -len(c["faces"]))
    if -1 in groups:
        out.append({"cluster_id": -1, "faces": groups[-1]})
    # Faces never clustered (e.g. added since the last run) show as unclustered too.
    loose = conn.execute(FACE_SQL + " WHERE f.status IN ('unknown', 'suggested') "
                         "AND f.cluster_id IS NULL ORDER BY f.id").fetchall()
    if loose:
        if out and out[-1]["cluster_id"] == -1:
            out[-1]["faces"].extend(face_json(r) for r in loose)
        else:
            out.append({"cluster_id": -1, "faces": [face_json(r) for r in loose]})
    return out


class ReclusterIn(BaseModel):
    min_size: int | None = None      # None = from Settings
    threshold: float | None = None


@app.post("/api/recluster")
def recluster(body: ReclusterIn, conn=Conn):
    n_sugg = match.suggest(conn, body.threshold)
    n = cluster.cluster(conn, body.min_size)
    return {"clusters": n, "suggestions": n_sugg}


# ---------------------------------------------------------------- face actions

class FacesIn(BaseModel):
    face_ids: list[int]


class AssignIn(FacesIn):
    person_id: int | None = None
    name: str | None = None


@app.post("/api/faces/assign")
def faces_assign(body: AssignIn, conn=Conn):
    try:
        pid = actions.person_id_for(conn, body.person_id, body.name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    actions.assign(conn, body.face_ids, pid)
    return {"person_id": pid, "suggestions": actions.resuggest(conn)}


@app.post("/api/faces/reject")
def faces_reject(body: FacesIn, conn=Conn):
    n = actions.reject(conn, body.face_ids)
    return {"rejected": n, "suggestions": actions.resuggest(conn)}


@app.post("/api/faces/ignore")
def faces_ignore(body: FacesIn, conn=Conn):
    actions.ignore(conn, body.face_ids)
    return {"ok": True}


@app.get("/api/faces/candidates")
def faces_candidates(conn=Conn):
    """Possible faces from the thorough scan, waiting for 'face' / 'not a face'.
    Sorted most face-like first, using earlier decisions (see candidates.py)."""
    rows = conn.execute(FACE_SQL + " WHERE f.candidate = 1 AND f.status != 'ignored' "
                        "ORDER BY i.path, f.id").fetchall()
    scores, info = candidates.score(conn)
    out = []
    for r in rows:
        s, likely = scores.get(r["id"], (0.0, None))
        out.append({**face_json(r), "score": s, "likely": likely})
    if info["active"]:
        out.sort(key=lambda f: -f["score"])
    return {"faces": out, "learning": info,
            "preselect": config.get(conn, "preselect_non_faces")}


# ---------------------------------------------------------------- settings

def _provider() -> str:
    try:
        return faces.active_provider()
    except Exception as e:  # model not downloaded yet, broken GPU runtime...
        return f"not available ({e})"


@app.get("/api/settings")
def settings_get(conn=Conn):
    return {
        "values": config.load(conn),
        "defaults": config.defaults(),
        "help": {k: v[2] for k, v in config.FIELDS.items()},
        "info": {
            "library_root": db.get_setting(conn, "library_root"),
            "data_dir": str(library.data_dir().resolve()),
            "provider": _provider(),
        },
    }


@app.put("/api/settings")
def settings_put(body: dict, conn=Conn):
    old = config.load(conn)
    try:
        new = config.save(conn, body)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if any(old[k] != new[k] for k in ("suggest_threshold", "keyword_autoconfirm")):
        actions.resuggest(conn)
    if old["min_cluster_size"] != new["min_cluster_size"]:
        cluster.cluster(conn)
    return settings_get(conn)


@app.post("/api/faces/verify")
def faces_verify(body: FacesIn, conn=Conn):
    actions.verify_faces(conn, body.face_ids)
    cluster.cluster(conn)
    return {"suggestions": actions.resuggest(conn)}


@app.post("/api/faces/unignore")
def faces_unignore(body: FacesIn, conn=Conn):
    actions.unignore(conn, body.face_ids)
    return {"suggestions": actions.resuggest(conn)}


@app.post("/api/faces/remove-from-cluster")
def faces_remove_from_cluster(body: FacesIn, conn=Conn):
    actions.remove_from_cluster(conn, body.face_ids)
    return {"ok": True}


@app.get("/api/faces/ignored")
def faces_ignored(conn=Conn):
    return [face_json(r) for r in conn.execute(FACE_SQL + " WHERE f.status = 'ignored' ORDER BY f.id")]


@app.get("/api/faces/{face_id}/thumb")
def face_thumb(face_id: int):
    _need_library()
    p = library.thumbs_dir() / f"{face_id}.jpg"
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, headers={"Cache-Control": "max-age=86400"})  # URL carries ?v=<db_token>


# ---------------------------------------------------------------- people

class PersonIn(BaseModel):
    name: str | None = None
    birth_year: int | None = None
    death_year: int | None = None
    notes: str | None = None
    cover_face_id: int | None = None
    name_from_year: int | None = None


@app.get("/api/people")
def people(conn=Conn):
    rows = conn.execute("""
        SELECT p.*,
          (SELECT COUNT(*) FROM faces f WHERE f.person_id = p.id AND f.status = 'confirmed') AS confirmed,
          (SELECT COUNT(*) FROM faces f WHERE f.person_id = p.id AND f.status = 'suggested') AS suggested,
          COALESCE(p.cover_face_id, (SELECT f.id FROM faces f WHERE f.person_id = p.id
                    AND f.status = 'confirmed' ORDER BY f.det_score DESC LIMIT 1)) AS cover,
          (SELECT COUNT(DISTINCT pk.photo_id) FROM photo_keywords pk JOIN keywords k
             ON k.id = pk.keyword_id WHERE k.person_id = p.id) AS photos,
          (SELECT group_concat(k.category, ', ') FROM keywords k WHERE k.person_id = p.id) AS groups
        FROM people p ORDER BY p.name""").fetchall()
    aliases = _aliases(conn)
    shown = _current_names(conn)
    cur = library.get_curator(conn)
    rel = family.labels(conn, cur["id"] if cur else None)
    return [{**dict(r), "aliases": aliases.get(r["id"], []), "relation": rel.get(r["id"]),
             "display_name": shown[r["id"]]} for r in rows]


def _aliases(conn: sqlite3.Connection, person_id: int | None = None) -> dict[int, list[dict]]:
    sql = "SELECT person_id, name, kind, from_year FROM person_names"
    args: tuple = ()
    if person_id is not None:
        sql, args = sql + " WHERE person_id = ?", (person_id,)
    out: dict[int, list[dict]] = {}
    for r in conn.execute(sql + " ORDER BY from_year IS NULL, from_year, name", args):
        out.setdefault(r["person_id"], []).append(
            {"name": r["name"], "kind": r["kind"], "from_year": r["from_year"]})
    return out


class AliasIn(BaseModel):
    name: str
    kind: str = "other"
    from_year: int | None = None


@app.put("/api/people/{pid}/aliases")
def person_aliases(pid: int, body: list[AliasIn], conn=Conn):
    """Replace the person's other names. The keyword in files is unchanged; a name with
    a year is shown for photos dated from that year on."""
    if conn.execute("SELECT 1 FROM people WHERE id = ?", (pid,)).fetchone() is None:
        raise HTTPException(404)
    clean: dict[str, AliasIn] = {}
    for a in body:
        name = a.name.strip()
        if not name:
            continue
        if a.kind not in ("birth", "married", "nickname", "other"):
            raise HTTPException(400, f"Unknown kind {a.kind!r}")
        if name.lower() in clean:
            raise HTTPException(400, f"{name!r} is listed twice")
        taken = conn.execute(
            "SELECT p.id FROM people p WHERE lower(p.name) = lower(?) AND p.id != ? UNION "
            "SELECT person_id FROM person_names WHERE lower(name) = lower(?) AND person_id != ?",
            (name, pid, name, pid)).fetchone()
        if taken or conn.execute("SELECT 1 FROM people WHERE id = ? AND lower(name) = lower(?)",
                                 (pid, name)).fetchone():
            raise HTTPException(409, f"{name!r} is already a name in this library")
        clean[name.lower()] = AliasIn(name=name, kind=a.kind, from_year=a.from_year)
    conn.execute("DELETE FROM person_names WHERE person_id = ?", (pid,))
    conn.executemany("INSERT INTO person_names(person_id, name, kind, from_year) VALUES (?, ?, ?, ?)",
                     [(pid, a.name, a.kind, a.from_year) for a in clean.values()])
    conn.commit()
    return _aliases(conn, pid).get(pid, [])


@app.post("/api/people")
def person_create(body: PersonIn, conn=Conn):
    if not body.name or not body.name.strip():
        raise HTTPException(400, "name required")
    pid = db.get_or_create_person(conn, body.name)
    conn.commit()
    return person_update(pid, body, conn)


@app.get("/api/people/{pid}")
def person(pid: int, conn=Conn):
    row = conn.execute("SELECT * FROM people WHERE id = ?", (pid,)).fetchone()
    if row is None:
        raise HTTPException(404)
    faces = [face_json(r) for r in conn.execute(
        FACE_SQL + " WHERE f.person_id = ? ORDER BY f.status, f.confidence DESC, f.id", (pid,))]
    kws = [dict(r) for r in conn.execute(
        "SELECT k.id, k.category, k.name, (SELECT COUNT(*) FROM photo_keywords pk "
        "WHERE pk.keyword_id = k.id) AS photos FROM keywords k WHERE k.person_id = ?", (pid,))]
    return {**dict(row), "keywords": kws, "aliases": _aliases(conn, pid).get(pid, []),
            "display_name": _current_names(conn)[pid],
            "relation": _relatives_json(conn, pid)["relation"],
            "confirmed": [f for f in faces if f["status"] == "confirmed"],
            "suggested": [f for f in faces if f["status"] == "suggested"]}


class RelativeIn(BaseModel):
    relation: str   # parent | child | partner: who the other person is to this one
    person_id: int | None = None
    name: str | None = None


def _relatives_json(conn: sqlite3.Connection, pid: int) -> dict:
    cur = library.get_curator(conn)
    lab = family.labels(conn, cur["id"] if cur else None)
    shown = _current_names(conn)
    out: dict = {"relation": lab.get(pid), "curator": cur}
    for kind, ids in family.relatives(conn, pid).items():
        out[kind] = [{"id": i, "name": shown[i], "relation": lab.get(i)} for i in ids]
    return out


@app.get("/api/people/{pid}/relatives")
def person_relatives(pid: int, conn=Conn):
    if conn.execute("SELECT 1 FROM people WHERE id = ?", (pid,)).fetchone() is None:
        raise HTTPException(404)
    return _relatives_json(conn, pid)


@app.post("/api/people/{pid}/relatives")
def person_relative_add(pid: int, body: RelativeIn, conn=Conn):
    """Link another person (existing, or a new name) as this person's parent, child or partner."""
    if body.person_id is None and not (body.name and body.name.strip()):
        raise HTTPException(400, "person_id or name required")
    other = body.person_id if body.person_id is not None else db.get_or_create_person(conn, body.name.strip())
    try:
        if body.relation == "parent":
            family.add(conn, "parent", other, pid)
        elif body.relation == "child":
            family.add(conn, "parent", pid, other)
        elif body.relation == "partner":
            family.add(conn, "partner", pid, other)
        else:
            raise ValueError(f"unknown relation {body.relation!r}")
    except ValueError as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    conn.commit()
    return _relatives_json(conn, pid)


@app.delete("/api/people/{pid}/relatives/{relation}/{other}")
def person_relative_remove(pid: int, relation: str, other: int, conn=Conn):
    if relation not in ("parent", "child", "partner"):
        raise HTTPException(400, f"unknown relation {relation!r}")
    if relation == "child":
        family.remove(conn, "parent", pid, other)
    else:
        family.remove(conn, relation, other, pid)
    conn.commit()
    return _relatives_json(conn, pid)


@app.get("/api/family-branches")
def family_branches(conn=Conn):
    """What writing branch keywords would do (nothing is changed)."""
    return actions.sync_branch_keywords(conn, apply=False)


@app.post("/api/family-branches")
def family_branches_apply(conn=Conn):
    """Write Family|<Branch> keywords into the photos (and remove ones that no longer apply)."""
    return actions.sync_branch_keywords(conn, apply=True)


@app.get("/api/family/{pid}")
def family_tree(pid: int, generations: int = 1, conn=Conn):
    """Nodes and links for the family tree around a person."""
    if conn.execute("SELECT 1 FROM people WHERE id = ?", (pid,)).fetchone() is None:
        raise HTTPException(404)
    gen = family.circle(conn, pid, max(1, min(generations, 4)))
    cur = library.get_curator(conn)
    lab = family.labels(conn, cur["id"] if cur else None)
    rows = conn.execute(f"""
        SELECT p.id, p.name, p.birth_year, p.death_year,
          COALESCE(p.cover_face_id, (SELECT f.id FROM faces f WHERE f.person_id = p.id
                    AND f.status = 'confirmed' ORDER BY f.det_score DESC LIMIT 1)) AS cover
        FROM people p WHERE p.id IN ({','.join('?' * len(gen))})""", list(gen)).fetchall()
    shown = _current_names(conn)
    nodes = [{**dict(r), "name": shown[r["id"]], "gen": gen[r["id"]], "relation": lab.get(r["id"])}
             for r in rows]
    return {"focus": pid, "nodes": nodes, "edges": family.edges_among(conn, set(gen)),
            "curator": cur["id"] if cur else None}


@app.patch("/api/people/{pid}")
def person_update(pid: int, body: PersonIn, conn=Conn):
    fields = body.model_dump(exclude_unset=True)
    if "name" in fields:
        name = (fields["name"] or "").strip()
        if not name:
            raise HTTPException(400, "name required")
        clash = conn.execute("SELECT id FROM people WHERE name = ? AND id != ?", (name, pid)).fetchone()
        if clash:
            raise HTTPException(409, f"'{name}' already exists - use merge instead")
        fields["name"] = name
    if fields:
        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE people SET {sets} WHERE id = ?", (*fields.values(), pid))
        conn.commit()
    if {"birth_year", "death_year"} & fields.keys():
        actions.resuggest(conn)
    return person(pid, conn)


class MergeIn(BaseModel):
    into: int


@app.post("/api/people/{pid}/merge")
def person_merge(pid: int, body: MergeIn, conn=Conn):
    actions.merge_people(conn, pid, body.into)
    actions.resuggest(conn)
    return {"person_id": body.into}


@app.delete("/api/people/{pid}")
def person_delete(pid: int, conn=Conn):
    conn.execute("UPDATE faces SET status = 'unknown', person_id = NULL, confidence = NULL "
                 "WHERE person_id = ?", (pid,))
    # Their keywords go too, unless they are on photos (the files still carry them).
    conn.execute("DELETE FROM keywords WHERE person_id = ? AND NOT EXISTS "
                 "(SELECT 1 FROM photo_keywords pk WHERE pk.keyword_id = keywords.id)", (pid,))
    conn.execute("DELETE FROM people WHERE id = ?", (pid,))
    conn.commit()
    actions.resuggest(conn)
    return {"ok": True}


# ---------------------------------------------------------------- photos

PHOTO_FILTERS = {
    "all": "1",
    "undated": "ph.date_text IS NULL",
    "unnamed": "EXISTS (SELECT 1 FROM faces f JOIN images i2 ON i2.id = f.image_id "
               "WHERE i2.photo_id = ph.id AND f.status IN ('unknown', 'suggested'))",
    "has_back": "EXISTS (SELECT 1 FROM images i2 WHERE i2.photo_id = ph.id AND i2.role = 'back')",
}


@app.get("/api/photos")
def photos(filter: str = "all", person_id: int | None = None, q: str | None = None,
           keyword_id: int | None = None, family_id: int | None = None, generations: int = 1,
           conn=Conn):
    where = [PHOTO_FILTERS.get(filter, "1")]
    params: list = []
    if family_id is not None:  # anyone in that person's family (see family.circle)
        ids = list(family.circle(conn, family_id, max(1, min(generations, 4))))
        marks = ",".join("?" * len(ids))
        where.append("(EXISTS (SELECT 1 FROM faces f JOIN images i2 ON i2.id = f.image_id "
                     f"WHERE i2.photo_id = ph.id AND f.person_id IN ({marks}) AND f.status = 'confirmed') "
                     "OR EXISTS (SELECT 1 FROM photo_keywords pk JOIN keywords k ON k.id = pk.keyword_id "
                     f"WHERE pk.photo_id = ph.id AND k.person_id IN ({marks})))")
        params += ids + ids
    if person_id is not None:  # a confirmed face, or a keyword naming them
        where.append("(EXISTS (SELECT 1 FROM faces f JOIN images i2 ON i2.id = f.image_id "
                     "WHERE i2.photo_id = ph.id AND f.person_id = ? AND f.status = 'confirmed') "
                     "OR EXISTS (SELECT 1 FROM photo_keywords pk JOIN keywords k ON k.id = pk.keyword_id "
                     "WHERE pk.photo_id = ph.id AND k.person_id = ?))")
        params += [person_id, person_id]
    if keyword_id is not None:
        where.append("EXISTS (SELECT 1 FROM photo_keywords pk WHERE pk.photo_id = ph.id "
                     "AND pk.keyword_id = ?)")
        params.append(keyword_id)
    if q:
        where.append("(i.path LIKE ? OR ph.caption LIKE ? OR ph.location LIKE ? OR ph.back_text LIKE ? "
                     "OR EXISTS (SELECT 1 FROM photo_keywords pk JOIN keywords k ON k.id = pk.keyword_id "
                     "WHERE pk.photo_id = ph.id AND k.name LIKE ?) "
                     "OR EXISTS (SELECT 1 FROM person_names pn JOIN keywords k ON k.person_id = pn.person_id "
                     "JOIN photo_keywords pk ON pk.keyword_id = k.id "
                     "WHERE pk.photo_id = ph.id AND pn.name LIKE ?))")
        params += [f"%{q}%"] * 4 + [f"%{q.replace(' ', '')}%", f"%{q}%"]
    rows = conn.execute(f"""
        SELECT ph.id, ph.date_text, ph.date_min, ph.location, i.id AS front_id, i.path,
          (SELECT COUNT(*) FROM faces f JOIN images i2 ON i2.id = f.image_id WHERE i2.photo_id = ph.id
             AND f.status != 'ignored') AS faces,
          (SELECT COUNT(*) FROM faces f JOIN images i2 ON i2.id = f.image_id WHERE i2.photo_id = ph.id
             AND f.status = 'confirmed') AS named
        FROM photos ph
        JOIN images i ON i.id = (SELECT id FROM images WHERE photo_id = ph.id
                                 ORDER BY role = 'front' DESC, id LIMIT 1)
        WHERE {' AND '.join(where)}
        ORDER BY ph.date_min IS NULL, ph.date_min, i.path""", params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["date"] = date_json(r["date_text"])
        out.append(d)
    return out


@app.get("/api/photos/{photo_id}/file-metadata")
def photo_file_metadata(photo_id: int, conn=Conn):
    """All EXIF / IPTC / XMP tags in the photo's front image, plus which ones this app
    writes: 'app' = the app's own (pm:), 'changed' = edited by the app (original saved),
    'managed' = the app updates it when you edit, but hasn't yet."""
    path = actions._front_path(conn, photo_id)
    if path is None or not path.exists():
        raise HTTPException(404)
    tags, warning = xmp.read_all_safe(path)
    x = tags["xmp"]
    app = {k: "app" for k in x if k.startswith("Xmp.pm.")}
    for key in xmp.MANAGED:
        if any(key in group for group in tags.values()):
            changed = xmp.ORIGINALS.get(key) in x or (
                key in xmp.KEYWORD_KEYS and xmp.ADDED in x)
            app[key] = "changed" if changed else "managed"
    return {"tags": tags, "app": app, "warning": warning}


@app.get("/api/photos/{photo_id}")
def photo(photo_id: int, conn=Conn):
    ph = conn.execute("SELECT * FROM photos WHERE id = ?", (photo_id,)).fetchone()
    if ph is None:
        raise HTTPException(404)
    images = [dict(r) for r in conn.execute(
        "SELECT id, role, path, width, height, is_bw FROM images WHERE photo_id = ? "
        "ORDER BY role = 'front' DESC, id", (photo_id,))]
    faces = [face_json(r) for r in conn.execute(
        FACE_SQL + " WHERE i.photo_id = ? ORDER BY f.x1", (photo_id,))]
    return {**dict(ph), "date": date_json(ph["date_text"]), "images": images, "faces": faces,
            "keywords": photo_keywords(conn, photo_id)}


def photo_keywords(conn: sqlite3.Connection, photo_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT k.id, k.category, k.name, k.kind, k.person_id, pk.source, p.name AS primary_name, "
        "p.name_from_year, CAST(substr(ph.date_min, 1, 4) AS INTEGER) AS photo_year, "
        + names.ALIAS_BLOB_SQL.format(pid="k.person_id") + " AS alias_blob "
        "FROM photo_keywords pk JOIN keywords k ON k.id = pk.keyword_id "
        "JOIN photos ph ON ph.id = pk.photo_id LEFT JOIN people p ON p.id = k.person_id "
        "WHERE pk.photo_id = ? ORDER BY k.kind = 'attribute', k.category, k.name", (photo_id,)).fetchall()
    out = []
    for r in rows:
        d = {k: r[k] for k in ("id", "category", "name", "kind", "person_id", "source")}
        d["display"] = _name_on_photo(r)
        out.append(d)
    return out


@app.get("/api/keywords")
def keyword_list(conn=Conn):
    rows = conn.execute(
        "SELECT k.id, k.category, k.name, k.kind, k.person_id, k.in_vocab, "
        "(SELECT COUNT(*) FROM photo_keywords pk WHERE pk.keyword_id = k.id) AS photos "
        "FROM keywords k ORDER BY k.category, k.name").fetchall()
    return [dict(r) for r in rows]


@app.delete("/api/keywords/{keyword_id}")
def keyword_delete(keyword_id: int, conn=Conn):
    """Delete a keyword that is on no photo (a mistake or an unused vocabulary entry)."""
    n = conn.execute("SELECT COUNT(*) FROM photo_keywords WHERE keyword_id = ?", (keyword_id,)).fetchone()[0]
    if n:
        raise HTTPException(409, f"On {n} photo(s) - remove it from them first")
    if not conn.execute("DELETE FROM keywords WHERE id = ?", (keyword_id,)).rowcount:
        raise HTTPException(404, "No such keyword")
    conn.commit()
    return {"ok": True}


class KeywordIn(BaseModel):
    keyword_id: int | None = None
    category: str | None = None
    name: str | None = None


def _keyword_from(conn: sqlite3.Connection, body: KeywordIn) -> int:
    if body.keyword_id is not None:
        return body.keyword_id
    if not body.category or not body.name or not body.name.strip():
        raise HTTPException(400, "keyword_id, or category and name, required")
    cat, name = body.category.strip(), body.name.strip()
    if keywords.kind_of(cat, conn) == "person":
        name = keywords.keyword_name(name)  # 'Ann Smith' -> 'AnnSmith', the collection's style
    return keywords.ensure(conn, cat, name)


@app.post("/api/keywords")
def keyword_create(body: KeywordIn, conn=Conn):
    kid = _keyword_from(conn, body)
    conn.commit()
    return dict(conn.execute("SELECT id, category, name, kind, person_id FROM keywords WHERE id = ?",
                             (kid,)).fetchone())


@app.post("/api/photos/{photo_id}/keywords")
def photo_keyword_add(photo_id: int, body: KeywordIn, conn=Conn):
    """Add a keyword to a photo (and its file). New keywords need category + name."""
    kid = _keyword_from(conn, body)
    if not actions.add_photo_keyword(conn, photo_id, kid):
        raise HTTPException(409, "Already on this photo, or the file could not be written")
    conn.commit()
    actions.resuggest(conn)  # a new person keyword narrows who the faces can be
    actions.auto_branches(conn, {photo_id})
    return photo_keywords(conn, photo_id)


@app.delete("/api/photos/{photo_id}/keywords/{keyword_id}")
def photo_keyword_remove(photo_id: int, keyword_id: int, conn=Conn):
    """Remove a keyword from a photo and its file - including ones that were already
    in the file (the UI asks first; `pm baseline restore` brings them back in testing)."""
    if not actions.remove_photo_keyword(conn, photo_id, keyword_id, only_app=False):
        raise HTTPException(404, "Not on this photo, or the file could not be written")
    conn.commit()
    actions.resuggest(conn)
    actions.auto_branches(conn, {photo_id})
    return photo_keywords(conn, photo_id)


class PhotoIn(BaseModel):
    date_text: str | None = None
    location: str | None = None
    caption: str | None = None
    back_text: str | None = None
    notes: str | None = None


@app.patch("/api/photos/{photo_id}")
def photo_update(photo_id: int, body: PhotoIn, conn=Conn):
    try:
        actions.update_photo(conn, photo_id, body.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(400, str(e))
    actions.resuggest(conn)  # date changes affect birth/death filtering
    return photo(photo_id, conn)


class BatchGetIn(BaseModel):
    photo_ids: list[int]


@app.post("/api/photos/batch-get")
def photos_batch_get(body: BatchGetIn, conn=Conn):
    """Editable fields + keywords for several photos (for the multi-photo editor)."""
    out = []
    for pid in body.photo_ids:
        r = conn.execute("SELECT id, date_text, location, caption FROM photos WHERE id = ?",
                         (pid,)).fetchone()
        if r:
            out.append({**dict(r), "date": date_json(r["date_text"]),
                        "keywords": photo_keywords(conn, pid)})
    return out


class BatchEditIn(BaseModel):
    photo_ids: list[int]
    fields: PhotoIn = PhotoIn()
    add_keyword_ids: list[int] = []
    remove_keyword_ids: list[int] = []


@app.post("/api/photos/batch-edit")
def photos_batch_edit(body: BatchEditIn, conn=Conn):
    """Apply the same changes to many photos (DB and files). Only fields the client
    sends are changed - the editor leaves '<mixed>' fields out."""
    fields = body.fields.model_dump(exclude_unset=True)
    text = fields.get("date_text")
    if text and text.strip() and dates.parse(text) is None:
        raise HTTPException(400, f"Can't understand date: {text!r}")
    added = removed = 0
    for pid in body.photo_ids:
        actions.update_photo(conn, pid, dict(fields))
        for kid in body.add_keyword_ids:
            added += actions.add_photo_keyword(conn, pid, kid)
        for kid in body.remove_keyword_ids:
            removed += actions.remove_photo_keyword(conn, pid, kid, only_app=False)
        conn.commit()
    actions.resuggest(conn)
    return {"photos": len(body.photo_ids), "keywords_added": added, "keywords_removed": removed}


@app.get("/api/dates/parse")
def parse_date(text: str = ""):
    return {"text": text, "date": date_json(text)}


# ---------------------------------------------------------------- adding photos

class IngestJob:
    """One background ingest at a time; the UI polls /api/ingest/status."""

    def __init__(self):
        self.lock = threading.Lock()
        self.state: dict = {"running": False}

    def start(self, folder: Path) -> bool:
        with self.lock:
            if self.state.get("running"):
                return False
            self.state = {"running": True, "stage": "Starting", "done": 0, "total": 0,
                          "result": None, "error": None}
        threading.Thread(target=self._run, args=(folder,), daemon=True).start()
        return True

    def _progress(self, stage: str, done: int, total: int) -> None:
        self.state.update(stage=stage, done=done, total=total)

    def _run(self, folder: Path) -> None:
        conn = db.connect(_need_library())
        try:
            result = ingest.ingest(conn, folder, library.thumbs_dir(), progress=self._progress)
            self._progress("Updating suggestions", 0, 0)
            result["suggestions"] = match.suggest(conn)
            result["clusters"] = cluster.cluster(conn)
            self.state.update(result=result)
        except Exception as e:  # report to UI instead of dying silently
            self.state.update(error=str(e))
        finally:
            conn.close()
            self.state["running"] = False


JOB = IngestJob()


@app.post("/api/ingest")
def ingest_start(conn=Conn):
    """Scan the whole library folder for new files."""
    root = db.get_setting(conn, "library_root")
    if root is None:
        raise HTTPException(400, "No library folder yet - create a library first")
    if not JOB.start(Path(root)):
        raise HTTPException(409, "An import is already running")
    return JOB.state


@app.get("/api/ingest/status")
def ingest_status():
    return JOB.state


@app.post("/api/upload")
def upload(files: list[UploadFile] = File(...), conn=Conn):
    """Copy uploaded photos into <library>/Imported/<date>/, then ingest them."""
    root = db.get_setting(conn, "library_root")
    if root is None:
        raise HTTPException(400, "No library folder yet - create a library first")
    if JOB.state.get("running"):
        raise HTTPException(409, "An import is already running")
    dest = Path(root) / "Imported" / date.today().isoformat()
    dest.mkdir(parents=True, exist_ok=True)
    saved, skipped = [], []
    for f in files:
        name = Path(f.filename or "").name
        if Path(name).suffix.lower() not in ingest.IMAGE_EXTS:
            skipped.append(name)
            continue
        target = dest / name
        n = 1
        while target.exists():  # never overwrite
            target = dest / f"{Path(name).stem} ({n}){Path(name).suffix}"
            n += 1
        with target.open("wb") as out:
            shutil.copyfileobj(f.file, out)
        saved.append(target.name)
    if saved:
        JOB.start(dest)
    return {"saved": len(saved), "skipped": skipped, "folder": dest.relative_to(root).as_posix()}


# ---------------------------------------------------------------- images

@app.get("/api/images/{image_id}")
def image(image_id: int, size: str = "large", conn=Conn):
    row = conn.execute("SELECT path FROM images WHERE id = ?", (image_id,)).fetchone()
    if row is None or size not in SIZES:
        raise HTTPException(404)
    cached = library.cache_dir() / size / f"{image_id}.jpg"
    if not cached.exists():
        src = db.library_root(conn) / row["path"]
        if not src.exists():
            raise HTTPException(404, f"missing file {row['path']}")
        cached.parent.mkdir(parents=True, exist_ok=True)
        img = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
        img.thumbnail((SIZES[size], SIZES[size]), Image.LANCZOS)
        img.save(cached, quality=85)
    return FileResponse(cached, headers={"Cache-Control": "max-age=86400"})  # URL carries ?v=<db_token>


# ---------------------------------------------------------------- libraries & facets

class ScanJob:
    """Background read of a folder's existing keywords (before a library is created)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.state: dict = {"running": False}

    def start(self, folder: Path) -> None:
        with self.lock:
            if self.state.get("running"):
                raise HTTPException(409, "A folder scan is already running")
            self.state = {"running": True, "folder": str(folder), "done": 0, "total": 0,
                          "result": None, "error": None}
        threading.Thread(target=self._run, args=(folder,), daemon=True).start()

    def _run(self, folder: Path) -> None:
        def progress(stage: str, done: int, total: int) -> None:
            self.state.update(done=done, total=total)
        try:
            self.state.update(result=library.scan(folder, progress))
        except Exception as e:
            self.state.update(error=str(e))
        finally:
            self.state["running"] = False


SCAN = ScanJob()


def _presets() -> dict:
    return {k: {"label": v["label"], "help": v["help"], "facets": v["facets"]}
            for k, v in library.PRESETS.items()}


@app.get("/api/library")
def library_get():
    path = library.db_path()
    out = {"open": path is not None, "presets": _presets(), "kinds": list(keywords.FACET_KINDS)}
    if path is not None:
        conn = db.connect(path)
        try:
            out.update(library.describe(conn))
        finally:
            conn.close()
    return out


@app.get("/api/fs/list")
def fs_list(path: str = ""):
    """Folders under `path` (drives / home when empty) for the folder picker. The server
    only listens on this computer."""
    if not path:
        if os.name == "nt":
            drives = [f"{c}:\\" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if Path(f"{c}:\\").exists()]
            return {"path": "", "parent": None, "dirs": [{"name": d, "path": d} for d in drives],
                    "images": 0, "has_library": False, "home": str(Path.home())}
        path = str(Path.home())
    p = Path(path).expanduser()
    if not p.is_dir():
        raise HTTPException(404, f"{path} is not a folder")
    dirs, images = [], 0
    try:
        for child in sorted(p.iterdir(), key=lambda c: c.name.lower()):
            if child.name.startswith(".") or child.name.startswith("$"):
                continue
            try:
                if child.is_dir():
                    dirs.append({"name": child.name, "path": str(child)})
                elif child.suffix.lower() in ingest.IMAGE_EXTS:
                    images += 1
            except OSError:
                continue
    except PermissionError:
        raise HTTPException(403, f"No permission to read {path}")
    parent = str(p.parent) if p.parent != p else ""
    return {"path": str(p), "parent": parent, "dirs": dirs, "images": images,
            "has_library": library.has_library(p), "home": str(Path.home())}


class FolderIn(BaseModel):
    folder: str


@app.post("/api/library/inspect")
def library_inspect(body: FolderIn):
    """Start reading the existing keywords of a folder (read-only). Poll /status."""
    p = Path(body.folder).expanduser()
    if not p.is_dir():
        raise HTTPException(400, f"{body.folder} is not a folder")
    if library.has_library(p):
        return {"existing": True, "folder": str(p.resolve())}
    SCAN.start(p)
    return {"existing": False, **SCAN.state}


@app.get("/api/library/inspect/status")
def library_inspect_status(preset: str = "family"):
    s = dict(SCAN.state)
    if s.get("result") is not None and preset in library.PRESETS:
        r = s["result"]
        s["facets"] = library.propose_facets(r, preset)
        top_paths = sorted(r["paths"].items(), key=lambda kv: -kv[1])[:200]
        s["result"] = {**r, "paths": dict(top_paths), "n_paths": len(r["paths"]),
                       "flat": dict(sorted(r["flat"].items(), key=lambda kv: -kv[1])[:100]),
                       "n_flat": len(r["flat"])}
    return s


class FacetIn(BaseModel):
    name: str
    kind: str = "other"


class CreateIn(BaseModel):
    folder: str
    facets: list[FacetIn]
    import_keywords: bool = True
    curator: str = ""


def _switch_to(root: Path) -> None:
    library.use_data_dir(library.data_dir_for(root))
    library.remember(root)


@app.post("/api/library/create")
def library_create(body: CreateIn):
    """Create a library in a folder: facets + vocabulary from the keywords in its files,
    then start importing the photos."""
    if JOB.state.get("running"):
        raise HTTPException(409, "An import is running; wait for it to finish")
    root = Path(body.folder).expanduser()
    found = None
    if body.import_keywords and SCAN.state.get("result") and \
            Path(SCAN.state["result"]["folder"]) == root.resolve():
        found = SCAN.state["result"]
    try:
        library.create(root, [f.model_dump() for f in body.facets], found, body.curator)
    except FileExistsError as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    _switch_to(root.resolve())
    JOB.start(root.resolve())
    return library_get()


@app.post("/api/library/open")
def library_open(body: FolderIn):
    if JOB.state.get("running"):
        raise HTTPException(409, "An import is running; wait for it to finish")
    root = Path(body.folder).expanduser().resolve()
    if not library.has_library(root):
        raise HTTPException(404, f"{root} has no Shoebox Archivist library yet")
    _switch_to(root)
    return library_get()


@app.post("/api/library/close")
def library_close():
    if JOB.state.get("running"):
        raise HTTPException(409, "An import is running; wait for it to finish")
    library.use_data_dir(None)
    return library_get()


class ResetIn(BaseModel):
    confirm: str = ""


@app.post("/api/library/reset")
def library_reset(body: ResetIn, conn=Conn):
    """Delete the app's data for the open library (database, thumbnails, facets). The
    photos, and keywords already written into them, are not touched."""
    if JOB.state.get("running"):
        raise HTTPException(409, "An import is running; wait for it to finish")
    if not library.is_managed():
        raise HTTPException(400, "This library's data folder is outside the photo folder; "
                                 "delete it yourself")
    root = Path(db.library_root(conn))
    if body.confirm != "reset":
        raise HTTPException(400, "Type 'reset' to confirm")
    conn.close()
    library.reset(root)
    JOB.state = {"running": False}
    SCAN.state = {"running": False}
    return library_get()


class CuratorIn(BaseModel):
    name: str = ""


@app.put("/api/library/curator")
def curator_put(body: CuratorIn, conn=Conn):
    library.set_curator(conn, body.name)
    return library.describe(conn)["curator"]


@app.get("/api/facets")
def facets_get(conn=Conn):
    return library.describe(conn)["facets"]


@app.put("/api/facets")
def facets_put(body: list[FacetIn], conn=Conn):
    try:
        keywords.set_facets(conn, [f.model_dump() for f in body])
    except ValueError as e:
        raise HTTPException(400, str(e))
    return library.describe(conn)["facets"]


@app.get("/api/keywords/export")
def keywords_export(conn=Conn):
    """Keywords.txt for Bridge / Lightroom (Keywords > Import)."""
    return Response(keywords.export_vocabulary(conn), media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="Keywords.txt"'})


# ---------------------------------------------------------------- static UI

if FRONTEND.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        return FileResponse(FRONTEND / "index.html")

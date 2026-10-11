"""State-changing operations shared by the CLI and the web API."""
from __future__ import annotations

import sqlite3
import sys
from collections.abc import Iterable

from . import dates, db, keywords, match, xmp


def _many(conn: sqlite3.Connection, sql: str, ids: Iterable[int], *extra) -> None:
    conn.executemany(sql, [(*extra, i) for i in ids])


def _ids_sql(ids: list[int]) -> str:
    return ",".join("?" * len(ids))


def _confirmed_pairs(conn: sqlite3.Connection, face_ids: list[int]) -> set[tuple[int, int]]:
    """(photo_id, person_id) for faces currently confirmed as someone."""
    if not face_ids:
        return set()
    return {(r[0], r[1]) for r in conn.execute(
        f"SELECT i.photo_id, f.person_id FROM faces f JOIN images i ON i.id = f.image_id "
        f"WHERE f.status = 'confirmed' AND f.person_id IS NOT NULL AND f.id IN ({_ids_sql(face_ids)})",
        face_ids)}


def _front_path(conn: sqlite3.Connection, photo_id: int):
    row = conn.execute("SELECT path FROM images WHERE photo_id = ? AND role = 'front' "
                       "ORDER BY id LIMIT 1", (photo_id,)).fetchone()
    return db.library_root(conn) / row["path"] if row else None


def add_photo_keyword(conn: sqlite3.Connection, photo_id: int, keyword_id: int) -> bool:
    """Put a keyword on a photo: in the DB and in the file. False if already there."""
    if conn.execute("SELECT 1 FROM photo_keywords WHERE photo_id = ? AND keyword_id = ?",
                    (photo_id, keyword_id)).fetchone():
        return False
    path = _front_path(conn, photo_id)
    try:
        if path:
            xmp.add_keywords(path, [keywords.path_of(conn, keyword_id)])
    except Exception as e:  # read-only / locked file: leave DB unchanged
        print(f"  could not write keyword to {path}: {e}", file=sys.stderr)
        return False
    conn.execute("INSERT INTO photo_keywords(photo_id, keyword_id, source) VALUES (?, ?, 'app')",
                 (photo_id, keyword_id))
    return True


def remove_photo_keyword(conn: sqlite3.Connection, photo_id: int, keyword_id: int,
                         only_app: bool = True) -> bool:
    """Take a keyword off a photo. By default only keywords this app added."""
    row = conn.execute("SELECT source FROM photo_keywords WHERE photo_id = ? AND keyword_id = ?",
                       (photo_id, keyword_id)).fetchone()
    if row is None or (only_app and row["source"] != "app"):
        return False
    path = _front_path(conn, photo_id)
    try:
        if path:
            xmp.remove_keywords(path, [keywords.path_of(conn, keyword_id)], only_app_added=only_app)
    except Exception as e:
        print(f"  could not update keywords in {path}: {e}", file=sys.stderr)
        return False
    conn.execute("DELETE FROM photo_keywords WHERE photo_id = ? AND keyword_id = ?",
                 (photo_id, keyword_id))
    return True


def _sync_keywords(conn: sqlite3.Connection, pairs: set[tuple[int, int]]) -> None:
    """Make each photo's person keywords agree with its confirmed faces: add the
    keyword for a confirmed person; drop an app-added one when nobody is left."""
    for photo_id, person_id in pairs:
        confirmed = conn.execute(
            "SELECT 1 FROM faces f JOIN images i ON i.id = f.image_id WHERE i.photo_id = ? "
            "AND f.person_id = ? AND f.status = 'confirmed'", (photo_id, person_id)).fetchone()
        if confirmed:
            if not keywords.photo_people(conn, photo_id) & {person_id}:
                add_photo_keyword(conn, photo_id, keywords.person_keyword(conn, person_id))
        else:
            for (kid,) in conn.execute("SELECT id FROM keywords WHERE person_id = ?", (person_id,)).fetchall():
                remove_photo_keyword(conn, photo_id, kid)
    conn.commit()


def assign(conn: sqlite3.Connection, face_ids: list[int], person_id: int) -> None:
    """Confirm faces as a person, and write the person's keyword to the photos."""
    before = _confirmed_pairs(conn, face_ids)
    _many(conn, "UPDATE faces SET person_id = ?, status = 'confirmed', confidence = NULL, "
                "label_source = 'user' WHERE id = ?", face_ids, person_id)
    conn.executemany("DELETE FROM rejections WHERE face_id = ? AND person_id = ?",
                     [(i, person_id) for i in face_ids])
    conn.commit()
    _sync_keywords(conn, before | _confirmed_pairs(conn, face_ids))


def reject(conn: sqlite3.Connection, face_ids: list[int]) -> int:
    """Reject the current name (suggested or confirmed) on faces. The pairing is
    remembered so it won't be suggested again; the face goes back to unknown.
    A person keyword this app added is removed from the file; the owner's are kept."""
    rows = conn.execute(
        f"SELECT id, person_id FROM faces WHERE person_id IS NOT NULL AND id IN "
        f"({_ids_sql(face_ids)})", face_ids).fetchall() if face_ids else []
    before = _confirmed_pairs(conn, face_ids)
    conn.executemany("INSERT OR IGNORE INTO rejections(face_id, person_id) VALUES (?, ?)",
                     [(r["id"], r["person_id"]) for r in rows])
    _many(conn, "UPDATE faces SET person_id = NULL, status = 'unknown', confidence = NULL, "
                "label_source = NULL WHERE id = ?", face_ids)
    conn.commit()
    _sync_keywords(conn, before)
    return len(rows)


def ignore(conn: sqlite3.Connection, face_ids: list[int]) -> None:
    """Not worth naming: strangers, paintings, false detections."""
    before = _confirmed_pairs(conn, face_ids)
    _many(conn, "UPDATE faces SET status = 'ignored', person_id = NULL, confidence = NULL, "
                "cluster_id = NULL WHERE id = ?", face_ids)
    conn.commit()
    _sync_keywords(conn, before)


def verify_faces(conn: sqlite3.Connection, face_ids: list[int]) -> None:
    """A thorough-scan candidate is a real face: let it be clustered and matched."""
    _many(conn, "UPDATE faces SET candidate = 0 WHERE id = ?", face_ids)
    conn.commit()


def unignore(conn: sqlite3.Connection, face_ids: list[int]) -> None:
    _many(conn, "UPDATE faces SET status = 'unknown' WHERE status = 'ignored' AND id = ?",
          face_ids)
    conn.commit()


def remove_from_cluster(conn: sqlite3.Connection, face_ids: list[int]) -> None:
    """Move faces to 'unclustered' (until the next re-cluster)."""
    _many(conn, "UPDATE faces SET cluster_id = -1 WHERE id = ?", face_ids)
    conn.commit()


def merge_people(conn: sqlite3.Connection, src: int, dst: int) -> None:
    conn.execute("UPDATE faces SET person_id = ? WHERE person_id = ?", (dst, src))
    conn.execute("UPDATE keywords SET person_id = ? WHERE person_id = ?", (dst, src))
    conn.execute("UPDATE OR IGNORE rejections SET person_id = ? WHERE person_id = ?", (dst, src))
    conn.execute("DELETE FROM people WHERE id = ?", (src,))
    conn.commit()


def set_photo_date(conn: sqlite3.Connection, photo_id: int, text: str | None) -> dates.FuzzyDate | None:
    """Set (or clear, with empty text) a fuzzy date. Raises ValueError if unparseable."""
    if not text or not text.strip():
        conn.execute("UPDATE photos SET date_text = NULL, date_min = NULL, date_max = NULL, "
                     "precision = NULL WHERE id = ?", (photo_id,))
        return None
    fd = dates.parse(text)
    if fd is None:
        raise ValueError(f"Can't understand date: {text!r}")
    conn.execute("UPDATE photos SET date_text = ?, date_min = ?, date_max = ?, precision = ? "
                 "WHERE id = ?", (fd.edtf, fd.date_min.isoformat(), fd.date_max.isoformat(),
                                  fd.precision, photo_id))
    return fd


def update_photo(conn: sqlite3.Connection, photo_id: int, fields: dict) -> None:
    """Set photo fields (date_text, location, caption, back_text, notes) in the DB,
    and write date / caption / location into the photo file. Raises ValueError for
    an unreadable date. Unchanged values are skipped."""
    cur = conn.execute("SELECT date_text, location, caption FROM photos WHERE id = ?",
                       (photo_id,)).fetchone()
    if cur is None:
        raise ValueError(f"No photo {photo_id}")
    to_file: dict = {}
    if "date_text" in fields:
        text = fields.pop("date_text")
        new = dates.parse(text) if text and text.strip() else None
        if text and text.strip() and new is None:
            raise ValueError(f"Can't understand date: {text!r}")
        if (new.edtf if new else None) != cur["date_text"]:
            set_photo_date(conn, photo_id, text)
            conn.execute("UPDATE photos SET date_source = ? WHERE id = ?",
                         ("user" if new else None, photo_id))
            to_file.update(date_created=dates.xmp_date(new) if new else None,
                           date_edtf=new.edtf if new else None)
    for key in ("caption", "location"):
        if key in fields:
            value = (fields[key] or "").strip() or None
            if value == cur[key]:
                fields.pop(key)
                continue
            fields[key] = value
            to_file["description" if key == "caption" else key] = value
            if key == "location":
                fields["location_source"] = "user" if value else None
    if fields:
        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE photos SET {sets} WHERE id = ?", (*fields.values(), photo_id))
    path = _front_path(conn, photo_id)
    if to_file and path:
        xmp.write_fields(path, **to_file)
    conn.commit()


def person_id_for(conn: sqlite3.Connection, person_id: int | None, name: str | None) -> int:
    if person_id is not None:
        return person_id
    if not name or not name.strip():
        raise ValueError("person_id or name required")
    pid = db.get_or_create_person(conn, name)
    conn.commit()
    return pid


def resuggest(conn: sqlite3.Connection) -> int:
    return match.suggest(conn)

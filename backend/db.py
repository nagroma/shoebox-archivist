"""SQLite schema and connection helpers.

Image paths are stored relative to the library root so a DB can move between
machines (Windows <-> macOS). Paths always use forward slashes.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS people (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    birth_year INTEGER,
    death_year INTEGER,
    notes      TEXT
);

-- A logical photograph. Has one or more images (front, back, ...).
CREATE TABLE IF NOT EXISTS photos (
    id         INTEGER PRIMARY KEY,
    date_text  TEXT,            -- EDTF, e.g. '1923-05', '192X', '1925~'
    date_min   TEXT,            -- ISO date, earliest possible
    date_max   TEXT,            -- ISO date, latest possible
    precision  TEXT,            -- day|month|year|decade|century|range|unknown
    back_text  TEXT,            -- verbatim transcription of the back
    caption    TEXT,
    lr_image_id INTEGER UNIQUE  -- Lightroom Adobe_images.id_local, for re-import
);

CREATE TABLE IF NOT EXISTS images (
    id        INTEGER PRIMARY KEY,
    photo_id  INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    role      TEXT NOT NULL CHECK (role IN ('front', 'back', 'other')),
    path      TEXT NOT NULL UNIQUE,   -- relative to library root, '/' separators
    sha1      TEXT NOT NULL,
    width     INTEGER,
    height    INTEGER,
    is_bw     INTEGER,            -- black & white scan (proxy for "historical")
    faces_scanned INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_images_photo ON images(photo_id);
CREATE INDEX IF NOT EXISTS idx_images_sha1 ON images(sha1);

CREATE TABLE IF NOT EXISTS faces (
    id         INTEGER PRIMARY KEY,
    image_id   INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
    x1 REAL NOT NULL, y1 REAL NOT NULL, x2 REAL NOT NULL, y2 REAL NOT NULL,  -- normalized 0..1
    det_score  REAL,
    embedding  BLOB,              -- float32[512], L2-normalized
    person_id  INTEGER REFERENCES people(id) ON DELETE SET NULL,
    status     TEXT NOT NULL DEFAULT 'unknown'
               CHECK (status IN ('unknown', 'suggested', 'confirmed', 'ignored')),
    confidence REAL,              -- similarity of the suggestion, if suggested
    cluster_id INTEGER,           -- latest clustering run, -1 = noise
    source     TEXT NOT NULL DEFAULT 'detector'  -- detector|manual|lightroom
);
CREATE INDEX IF NOT EXISTS idx_faces_image ON faces(image_id);
CREATE INDEX IF NOT EXISTS idx_faces_person ON faces(person_id);

-- "This face is NOT this person" - negative examples from rejected suggestions.
CREATE TABLE IF NOT EXISTS rejections (
    face_id   INTEGER NOT NULL REFERENCES faces(id) ON DELETE CASCADE,
    person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    PRIMARY KEY (face_id, person_id)
);

-- Keyword vocabulary, mirrored from the files' lr:hierarchicalSubject ('Category|Name').
-- kind: person|family|event|place|subject|scouts|attribute|other (see keywords.py).
CREATE TABLE IF NOT EXISTS keywords (
    id        INTEGER PRIMARY KEY,
    category  TEXT NOT NULL,
    name      TEXT NOT NULL,
    kind      TEXT NOT NULL,
    person_id INTEGER REFERENCES people(id) ON DELETE SET NULL,  -- for person keywords
    in_vocab  INTEGER NOT NULL DEFAULT 0,   -- listed in Keywords.txt
    UNIQUE (category, name)
);
CREATE INDEX IF NOT EXISTS idx_keywords_person ON keywords(person_id);

-- Keywords on a photo. source: 'file' = already in the file when ingested (the owner's),
-- 'app' = written to the file by this app (also listed in the file's pm:AddedKeywords).
CREATE TABLE IF NOT EXISTS photo_keywords (
    photo_id   INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    keyword_id INTEGER NOT NULL REFERENCES keywords(id) ON DELETE CASCADE,
    source     TEXT NOT NULL DEFAULT 'file',
    PRIMARY KEY (photo_id, keyword_id)
);
CREATE INDEX IF NOT EXISTS idx_photo_keywords_kw ON photo_keywords(keyword_id);

-- Suggestions from back OCR, Lightroom keywords, etc. awaiting review.
CREATE TABLE IF NOT EXISTS suggestions (
    id       INTEGER PRIMARY KEY,
    photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    kind     TEXT NOT NULL CHECK (kind IN ('name', 'date', 'place', 'caption')),
    value    TEXT NOT NULL,
    source   TEXT NOT NULL,      -- back_ocr|lightroom|face_match
    status   TEXT NOT NULL DEFAULT 'pending'
             CHECK (status IN ('pending', 'accepted', 'rejected'))
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: the web API opens one connection per request, but
    # FastAPI may run the dependency and the endpoint on different worker threads.
    conn = sqlite3.connect(db_path, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    _migrate(conn)
    if get_setting(conn, "db_token") is None:
        # Changes whenever the DB is recreated; image URLs include it so browsers never
        # show a cached thumbnail of a previous library under a reused face/image id.
        import uuid
        set_setting(conn, "db_token", uuid.uuid4().hex[:12])
        conn.commit()
    return conn


# Columns added after the first schema version: (table, column, type).
MIGRATIONS = [
    # 1 = found only by a thorough-scan extra pass (rotated / enlarged / contrast); often
    # not a face at all. Kept out of clustering and matching until someone says it is.
    ("faces", "candidate", "INTEGER NOT NULL DEFAULT 0"),
    ("photos", "location", "TEXT"),
    ("photos", "notes", "TEXT"),
    ("people", "cover_face_id", "INTEGER"),
    ("photos", "date_source", "TEXT"),       # xmp | exif | user | back_ocr
    ("photos", "taken_at", "TEXT"),          # full EXIF timestamp, when known
    ("photos", "gps_lat", "REAL"),
    ("photos", "gps_lon", "REAL"),
    ("photos", "location_source", "TEXT"),   # gps | user
    ("images", "camera", "TEXT"),
    ("images", "meta_read", "INTEGER NOT NULL DEFAULT 0"),
    # How a face got its name: user (clicked) | keyword (only face in a photo keyworded
    # with one person) | match (suggestion from face similarity).
    ("faces", "label_source", "TEXT"),
    ("photos", "date_original", "TEXT"),     # raw date from the file, before rules
]


def _migrate(conn: sqlite3.Connection) -> None:
    for table, col, typ in MIGRATIONS:
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if col not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
    conn.commit()


def get_setting(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def library_root(conn: sqlite3.Connection) -> Path:
    root = get_setting(conn, "library_root")
    if root is None:
        raise RuntimeError("Library root not set; run 'ingest' first.")
    return Path(root)


def get_or_create_person(conn: sqlite3.Connection, name: str) -> int:
    name = name.strip()
    row = conn.execute("SELECT id FROM people WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    return conn.execute("INSERT INTO people(name) VALUES(?)", (name,)).lastrowid

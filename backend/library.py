"""Libraries: a photo folder plus this app's own data about it.

The app keeps everything it knows (database, face thumbnails, preview cache, keyword
facets) in `<library folder>/.shoebox/`. Deleting that folder returns the photo folder to
a plain folder (`reset`); the photos themselves, and any keywords already written into
them, stay as they are. Dot-folders are ignored by ingest, so the data never counts as photos.

`PM_DATA=<dir>` still points the app at a data folder outside the library (older setup).
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from . import db, ingest, keywords, xmp

LIB_DIR = ".shoebox"

# Starting points offered when a library is created. Facets are plain data: the person
# creating the library can add, remove and retype them, and each library keeps its own.
PRESETS: dict[str, dict] = {
    "family": {
        "label": "Family archive",
        "help": "People, community groups, events, places, subjects, format, curation, source",
        "facets": [
            {"name": "People", "kind": "person"},
            {"name": "Community", "kind": "other"},
            {"name": "Events", "kind": "event"},
            {"name": "Places", "kind": "place"},
            {"name": "Subjects", "kind": "subject"},
            {"name": "Format", "kind": "attribute"},
            {"name": "Curation", "kind": "attribute"},
            {"name": "Source", "kind": "other"},
        ],
    },
    "blank": {
        "label": "Start empty",
        "help": "No facets; add them as you go (a People group is created when you name a face)",
        "facets": [],
    },
}


# ------------------------------------------------------------------ where things live

def data_dir_for(root: Path) -> Path:
    return Path(root) / LIB_DIR


def has_library(root: Path) -> bool:
    return (data_dir_for(root) / "library.db").exists()


_current: Path | None = None   # data directory of the open library


def use_data_dir(path: Path | None) -> None:
    global _current
    _current = Path(path) if path else None


def data_dir() -> Path | None:
    return _current


def db_path() -> Path | None:
    return _current / "library.db" if _current else None


def thumbs_dir() -> Path:
    assert _current, "no library open"
    return _current / "thumbs"


def cache_dir() -> Path:
    assert _current, "no library open"
    return _current / "cache"


def is_managed(data: Path | None = None) -> bool:
    """True when the open library's data lives in its own `.shoebox` folder (so it can be reset)."""
    d = data or _current
    return bool(d) and d.name == LIB_DIR


# ------------------------------------------------------------------ remembering the last library

def _state_file() -> Path:
    home = Path(os.environ.get("PM_HOME") or Path.home() / ".shoebox-archivist")
    return home / "state.json"


def remember(root: Path | None) -> None:
    f = _state_file()
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"last": str(root) if root else None}), encoding="utf-8")
    except OSError:
        pass


def last_library() -> Path | None:
    try:
        last = json.loads(_state_file().read_text(encoding="utf-8")).get("last")
    except (OSError, ValueError):
        return None
    return Path(last) if last and has_library(Path(last)) else None


def open_startup(legacy_dir: Path | None = None) -> Path | None:
    """Choose the library to open when the server starts: the last one used, else an
    older ./data folder if it has a database, else none (the UI shows the setup page)."""
    last = last_library()
    if last and (data_dir_for(last) / "library.db").exists():  # folder may have moved
        use_data_dir(data_dir_for(last))
    elif legacy_dir and (legacy_dir / "library.db").exists():
        use_data_dir(legacy_dir)
    return _current


# ------------------------------------------------------------------ inspecting a folder

Progress = Callable[[str, int, int], None]


def scan(folder: Path, progress: Progress | None = None) -> dict:
    """Read the keywords already in a folder's photos (read-only). Returns JSON-able:
    images, with_keywords, paths {hierarchical keyword: photos}, flat {keyword: photos}
    (keywords that aren't part of a hierarchy), top {first segment: photos}."""
    folder = Path(folder).resolve()
    images = ingest.find_images(folder, folder)
    paths: Counter = Counter()
    flat: Counter = Counter()
    top: Counter = Counter()
    with_kw = 0
    for i, p in enumerate(images, 1):
        x = xmp.read(p)
        hier = set(x.keywords)
        segments = {s for kw in hier for s in kw.split("|")}
        loose = {kw for kw in [*x.flat, *x.other] if kw not in segments}
        paths.update(hier)
        flat.update(loose)
        top.update({keywords.top_level(kw) for kw in hier})
        with_kw += bool(hier or loose)
        if progress and (i % 10 == 0 or i == len(images)):
            progress("Reading keywords", i, len(images))
    return {"folder": str(folder), "images": len(images), "with_keywords": with_kw,
            "paths": dict(paths), "flat": dict(flat), "top": dict(top)}


def propose_facets(found: dict | None, preset: str = "family") -> list[dict]:
    """Facets for a new library: the preset's, plus every top-level keyword group found
    in the files that the preset doesn't already have (kind guessed from its name)."""
    facets = [{**f, "found": 0, "from_files": False} for f in PRESETS[preset]["facets"]]
    by_name = {f["name"].lower(): f for f in facets}
    for name, n in sorted((found or {}).get("top", {}).items()):
        f = by_name.get(name.lower())
        if f:
            f["found"] = n
        else:
            facets.append({"name": name, "kind": keywords.guess_kind(name),
                           "found": n, "from_files": True})
    return facets


# ------------------------------------------------------------------ create / reset

CURATOR_SETTING = "curator_person_id"


def set_curator(conn: sqlite3.Connection, name: str) -> int | None:
    """The person this library is organised around (the 'home person': generation, side
    of the family and relationship labels are measured from them). Empty name clears it."""
    name = name.strip()
    if not name:
        conn.execute("DELETE FROM settings WHERE key = ?", (CURATOR_SETTING,))
        conn.commit()
        return None
    pid = db.get_or_create_person(conn, name)
    db.set_setting(conn, CURATOR_SETTING, str(pid))
    conn.commit()
    return pid


def get_curator(conn: sqlite3.Connection) -> dict | None:
    pid = db.get_setting(conn, CURATOR_SETTING)
    row = conn.execute("SELECT id, name FROM people WHERE id = ?", (pid,)).fetchone() if pid else None
    return dict(row) if row else None


def create(root: Path, facets: list[dict], found: dict | None = None,
           curator: str = "") -> Path:
    """Create the data folder, configure facets, and seed the vocabulary with the
    hierarchical keywords found in the files. Returns the data directory.
    Photos are not modified. Raises FileExistsError if the folder already has a library."""
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError(f"{root} is not a folder")
    if has_library(root):
        raise FileExistsError(f"{root} already has a Shoebox Archivist library")
    data = data_dir_for(root)
    data.mkdir(exist_ok=True)
    conn = db.connect(data / "library.db")
    try:
        db.set_setting(conn, "library_root", str(root))
        keywords.set_facets(conn, [{"name": f["name"], "kind": f["kind"]} for f in facets])
        for path in (found or {}).get("paths", {}):
            category, name = keywords.split(path)
            if category:
                keywords.ensure(conn, category, name, in_vocab=True)
        set_curator(conn, curator)
        conn.commit()
    except Exception:
        conn.close()
        shutil.rmtree(data, ignore_errors=True)
        raise
    conn.close()
    return data


def reset(root: Path) -> None:
    """Forget everything the app knows about this folder (database, thumbnails, cache,
    facets). Photos and the keywords inside them are untouched."""
    data = data_dir_for(root)
    if data.name != LIB_DIR:  # paranoia: only ever delete our own folder
        raise ValueError("not a library data folder")
    shutil.rmtree(data)
    if _current and _current.resolve() == data.resolve():
        use_data_dir(None)
    last = last_library_raw()
    if last and Path(last).resolve() == Path(root).resolve():
        remember(None)


def last_library_raw() -> str | None:
    try:
        return json.loads(_state_file().read_text(encoding="utf-8")).get("last")
    except (OSError, ValueError):
        return None


def describe(conn: sqlite3.Connection) -> dict:
    """Facets and counts of the open library, for the UI."""
    return {
        "root": db.get_setting(conn, "library_root"),
        "data_dir": str(_current.resolve()) if _current else None,
        "managed": is_managed(),
        "curator": get_curator(conn),
        "facets": [{**f, "keywords": keywords._facet_keyword_count(conn, f["name"])}
                   for f in keywords.get_facets(conn)],
    }

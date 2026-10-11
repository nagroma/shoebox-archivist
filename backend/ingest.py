"""Walk a folder, pair fronts with backs, register images, detect faces."""
from __future__ import annotations

import hashlib
import re
import sqlite3
import sys
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

from . import config, db, faces

# Keyword list (Lightroom "Export Keywords" format) kept at the library root.
VOCABULARY_FILE = "Keywords.txt"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}

# Filename stem suffixes that mark the back / front of a scanned print.
# e.g. "0012_b.jpg", "0012-back.tif", "Smith 1923 reverse.jpg"
BACK_SUFFIX = re.compile(r"[ _-](b|back|reverse|verso|bk)$", re.I)
FRONT_SUFFIX = re.compile(r"[ _-](a|f|front|recto)$", re.I)


def rel_path(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root).as_posix()


def sha1_of(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def classify(path: Path) -> tuple[str, str]:
    """Return (role, pairing key). Key = directory + stem without front/back suffix."""
    stem = path.stem
    if BACK_SUFFIX.search(stem):
        return "back", f"{path.parent}/{BACK_SUFFIX.sub('', stem).lower()}"
    return "front", f"{path.parent}/{FRONT_SUFFIX.sub('', stem).lower()}"


# Folders other photo apps keep inside a library: previews/caches, not photos.
# (LightCraft: thumbs/, Interop/; Lightroom: *.lrdata; Synology: @eaDir; macOS: .*)
IGNORE_DIRS = {"thumbs", "interop", "@eadir", "previews", "cache"}
IGNORE_DIR_SUFFIXES = (".lrdata",)


def is_ignored(rel: Path) -> bool:
    """True if any folder in this library-relative path is an app cache or hidden."""
    for part in rel.parts[:-1]:
        low = part.lower()
        if low.startswith(".") or low in IGNORE_DIRS or low.endswith(IGNORE_DIR_SUFFIXES):
            return True
    return rel.name.startswith(".")


def find_images(folder: Path, root: Path) -> list[Path]:
    return sorted(
        p for p in folder.rglob("*")
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS
        and not is_ignored(p.resolve().relative_to(root))
    )


def prune_ignored(conn: sqlite3.Connection, thumbs: Path) -> tuple[int, list[str]]:
    """Forget images that live in ignored folders (e.g. imported before the ignore
    rules existed). Images with confirmed faces are kept and reported instead.
    Returns (removed, kept_paths)."""
    removed, kept = 0, []
    for row in conn.execute("SELECT id, photo_id, path FROM images").fetchall():
        if not is_ignored(Path(row["path"])):
            continue
        confirmed = conn.execute("SELECT COUNT(*) FROM faces WHERE image_id = ? "
                                 "AND status = 'confirmed'", (row["id"],)).fetchone()[0]
        if confirmed:
            kept.append(row["path"])
            continue
        for f in conn.execute("SELECT id FROM faces WHERE image_id = ?", (row["id"],)).fetchall():
            (thumbs / f"{f['id']}.jpg").unlink(missing_ok=True)
        conn.execute("DELETE FROM images WHERE id = ?", (row["id"],))  # cascades to faces
        removed += 1
    conn.execute("DELETE FROM photos WHERE id NOT IN (SELECT photo_id FROM images)")
    conn.commit()
    return removed, kept


def register_images(conn: sqlite3.Connection, root: Path, folder: Path) -> tuple[int, int]:
    """Add new images to the DB, grouping front/back into photos.

    Returns (new_images, skipped_duplicates).
    """
    groups: dict[str, dict[str, list[Path]]] = defaultdict(lambda: {"front": [], "back": []})
    for p in find_images(folder, root):
        role, key = classify(p)
        groups[key][role].append(p)

    known = {r["path"] for r in conn.execute("SELECT path FROM images")}
    added = dupes = 0
    for key, g in groups.items():
        new_fronts = [p for p in g["front"] if rel_path(p, root) not in known]
        new_backs = [p for p in g["back"] if rel_path(p, root) not in known]
        if not new_fronts and not new_backs:
            continue

        # Photo to attach backs to: existing photo of an already-known front, else a new one.
        photo_for_backs = None
        for p in g["front"]:
            row = conn.execute("SELECT photo_id FROM images WHERE path = ?",
                               (rel_path(p, root),)).fetchone()
            if row:
                photo_for_backs = row["photo_id"]
                break

        for p in new_fronts + new_backs:
            digest = sha1_of(p)
            dup = conn.execute("SELECT path FROM images WHERE sha1 = ?", (digest,)).fetchone()
            if dup:
                print(f"  duplicate of {dup['path']}: {rel_path(p, root)}", file=sys.stderr)
                dupes += 1
                continue
            role = "back" if p in new_backs else "front"
            if role == "front" or photo_for_backs is None:
                photo_id = conn.execute("INSERT INTO photos DEFAULT VALUES").lastrowid
                if photo_for_backs is None:
                    photo_for_backs = photo_id
            else:
                photo_id = photo_for_backs
            conn.execute(
                "INSERT INTO images(photo_id, role, path, sha1) VALUES (?, ?, ?, ?)",
                (photo_id, role, rel_path(p, root), digest),
            )
            added += 1
    conn.commit()
    return added, dupes


Progress = Callable[[str, int, int], None]  # (stage, done, total)


def _print_progress(stage: str, done: int, total: int) -> None:
    if done == total or done % 25 == 0:
        print(f"  {stage}: {done}/{total}")


def read_metadata(conn: sqlite3.Connection, root: Path,
                  progress: Progress = _print_progress) -> int:
    """Read keywords, caption and date from each new file's XMP, then fill gaps
    from EXIF (camera date, GPS). Never overwrites anything the user entered.
    Returns the number of photos that got a date."""
    from . import actions, exif, keywords, xmp
    todo = conn.execute("SELECT id, path, photo_id, role FROM images WHERE meta_read = 0 "
                        "ORDER BY role = 'front' DESC, id").fetchall()
    n = 0
    for k, row in enumerate(todo, 1):
        path, photo_id = root / row["path"], row["photo_id"]
        x = xmp.read(path)
        # Hierarchical keywords, plus any flat / IPTC / Windows keyword that isn't part of one
        segments = {s for kw in x.keywords for s in kw.split("|")}
        extra = [kw for kw in dict.fromkeys(x.flat + x.other) if kw not in segments]
        for kw in x.keywords + extra:
            kid = keywords.resolve(conn, kw)
            source = "app" if kw in x.app_added else "file"
            conn.execute("INSERT OR IGNORE INTO photo_keywords(photo_id, keyword_id, source) "
                         "VALUES (?, ?, ?)", (photo_id, kid, source))
        info = exif.read(path)
        conn.execute("UPDATE images SET camera = ?, meta_read = 1 WHERE id = ?",
                     (info.camera, row["id"]))
        if row["role"] != "front":
            conn.commit()
            continue
        ph = conn.execute("SELECT date_text, gps_lat, location, caption FROM photos WHERE id = ?",
                          (photo_id,)).fetchone()
        if x.description and not ph["caption"]:
            conn.execute("UPDATE photos SET caption = ? WHERE id = ?", (x.description, photo_id))
        if x.location and not ph["location"]:
            conn.execute("UPDATE photos SET location = ?, location_source = 'user' WHERE id = ?",
                         (x.location, photo_id))
        tags = {xmp.leaf(kw) for kw in x.keywords} | set(x.flat) | set(x.other)
        edtf = x.date_edtf or keywords.date_rule(x.date_created, tags)
        if ph["date_text"] is None and edtf:
            actions.set_photo_date(conn, photo_id, edtf)
            conn.execute("UPDATE photos SET date_source = 'xmp', date_original = ? WHERE id = ?",
                         (x.date_created, photo_id))
            n += 1
        elif ph["date_text"] is None and info.taken and not x.date_created:
            actions.set_photo_date(conn, photo_id, info.taken.date().isoformat())
            conn.execute("UPDATE photos SET date_source = 'exif', taken_at = ? WHERE id = ?",
                         (info.taken.isoformat(), photo_id))
            n += 1
        if info.lat is not None and ph["gps_lat"] is None:
            conn.execute("UPDATE photos SET gps_lat = ?, gps_lon = ? WHERE id = ?",
                         (info.lat, info.lon, photo_id))
            if not ph["location"]:
                place = exif.place_name(info.lat, info.lon)
                if place:
                    conn.execute("UPDATE photos SET location = ?, location_source = 'gps' "
                                 "WHERE id = ?", (place, photo_id))
        conn.commit()
        progress("Reading keywords & dates", k, len(todo))
    return n


def scan_faces(conn: sqlite3.Connection, root: Path, thumbs: Path,
               det_size: int = faces.DEFAULT_DET_SIZE,
               progress: Progress = _print_progress, thorough: bool | None = None) -> tuple[int, int]:
    """Detect faces on all un-scanned front images. Returns (images, new faces).
    On a re-scan, faces that are already known (same place) are kept and not added again.
    thorough=None uses the detection mode from Settings; the extra passes always follow Settings."""
    todo = conn.execute(
        "SELECT id, path FROM images WHERE role = 'front' AND faces_scanned = 0"
    ).fetchall()
    if not todo:
        return 0, 0
    thumbs.mkdir(parents=True, exist_ok=True)
    cfg = config.load(conn)
    if thorough is None:
        thorough = cfg["detection_mode"] == "thorough"
    passes = dict(clahe_retry=cfg["pass_contrast"], enlarged=cfg["pass_enlarged"],
                  rotated=cfg["pass_rotated"])
    mode = "thorough" if thorough else "fast"
    print(f"Detecting faces in {len(todo)} images ({mode}, provider: {faces.active_provider()})")
    n_faces = 0
    for i, row in enumerate(todo, 1):
        path = root / row["path"]
        try:
            img = faces.load_image(path)
        except Exception as e:  # corrupt / unsupported file
            print(f"  cannot read {row['path']}: {e}", file=sys.stderr)
            conn.execute("UPDATE images SET faces_scanned = 1 WHERE id = ?", (row["id"],))
            conn.commit()
            continue
        known = [tuple(r) for r in conn.execute(
            "SELECT x1, y1, x2, y2 FROM faces WHERE image_id = ?", (row["id"],))]
        found = [f for f in faces.detect(img, det_size=det_size, thorough=thorough, **passes)
                 if not any(faces.same_face(f.bbox, k) for k in known)]
        conn.execute(
            "UPDATE images SET width = ?, height = ?, is_bw = ?, faces_scanned = 1 WHERE id = ?",
            (*img.size, faces.is_grayscale(img), row["id"]),
        )
        for f in found:
            face_id = conn.execute(
                "INSERT INTO faces(image_id, x1, y1, x2, y2, det_score, embedding, candidate) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (row["id"], *f.bbox, f.det_score, f.embedding.tobytes(), int(f.candidate)),
            ).lastrowid
            faces.crop_face(img, f.bbox).save(thumbs / f"{face_id}.jpg", quality=85)
        n_faces += len(found)
        conn.commit()
        progress("Finding faces", i, len(todo))
    return len(todo), n_faces


def ingest(conn: sqlite3.Connection, folder: Path, thumbs: Path,
           det_size: int = faces.DEFAULT_DET_SIZE,
           progress: Progress = _print_progress, thorough: bool | None = None) -> dict:
    folder = folder.resolve()
    root = db.get_setting(conn, "library_root")
    if root is None:
        db.set_setting(conn, "library_root", str(folder))
        conn.commit()
        root = str(folder)
    root_path = Path(root)
    if not folder.is_relative_to(root_path):
        raise ValueError(f"{folder} is outside the library root {root_path}")
    progress("Looking for new files", 0, 0)
    pruned, kept = prune_ignored(conn, thumbs)
    if pruned:
        print(f"Removed {pruned} preview/cache images that aren't photos")
    for k in kept:
        print(f"  kept {k} (in an ignored folder but has named faces)", file=sys.stderr)
    vocab = root_path / VOCABULARY_FILE
    if vocab.exists():
        from . import keywords
        print(f"Loaded {keywords.load_vocabulary(conn, vocab)} keywords from {VOCABULARY_FILE}")
    added, dupes = register_images(conn, root_path, folder)
    print(f"Registered {added} new images ({dupes} duplicates skipped)")
    dated = read_metadata(conn, root_path, progress)
    print(f"Dated {dated} photos from file metadata")
    n_img, n_faces = scan_faces(conn, root_path, thumbs, det_size, progress, thorough)
    print(f"Scanned {n_img} images, found {n_faces} faces")
    return {"added": added, "duplicates": dupes, "dated": dated, "pruned": pruned,
            "scanned": n_img, "faces": n_faces}

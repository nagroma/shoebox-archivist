"""Repair a face box and crop after the source scan was rotated externally."""
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory

from . import db, faces


def _box(row):
    return row["x1"], row["y1"], row["x2"], row["y2"]


def _has_decision(row):
    return row["status"] in {"confirmed", "ignored"}


def repair(conn, face_id: int, thumbs: Path, *, rotate: bool) -> int:
    """Rebuild one crop from the current scan, optionally turning its box 180 degrees."""
    original = conn.execute(
        "SELECT f.*, i.path FROM faces f JOIN images i ON i.id=f.image_id WHERE f.id=?", (face_id,)
    ).fetchone()
    if original is None:
        raise ValueError("That face is no longer on this scan")
    box = _box(original)
    keeper = detection = original
    duplicate = None
    if rotate:
        x1, y1, x2, y2 = box
        box = (1 - x2, 1 - y2, 1 - x1, 1 - y1)
        overlaps = [row for row in conn.execute(
            "SELECT * FROM faces WHERE image_id=? AND id!=?", (original["image_id"], face_id)
        ) if faces.same_face(box, _box(row))]
        if len(overlaps) > 1:
            raise ValueError("Several detections overlap the proposed box. Review those faces first.")
        if overlaps:
            detection = overlaps[0]
            if _has_decision(original) and _has_decision(detection) and (
                original["status"], original["person_id"]
            ) != (detection["status"], detection["person_id"]):
                raise ValueError("The detections have different face decisions. Review their labels before merging.")
            duplicate = detection
            if _has_decision(detection) and (not _has_decision(original) or
                (detection["label_source"] == "user" and original["label_source"] != "user")):
                keeper, duplicate = detection, original
            box = _box(detection)

    image = faces.load_image(db.library_root(conn) / original["path"])
    crop = faces.crop_face(image, box)
    thumbs.mkdir(parents=True, exist_ok=True)
    target = thumbs / f"{keeper['id']}.jpg"
    with TemporaryDirectory(dir=thumbs) as work:
        replacement = Path(work) / "crop.jpg"
        previous = Path(work) / "previous.jpg"
        crop.save(replacement, quality=85)
        if target.exists():
            copyfile(target, previous)
        replaced = False
        try:
            with conn:
                if rotate:
                    embedding = detection["embedding"] if detection["embedding"] is not None else original["embedding"]
                    conn.execute(
                        "UPDATE faces SET x1=?, y1=?, x2=?, y2=?, embedding=?, det_score=?, "
                        "candidate=?, cluster_id=NULL WHERE id=?",
                        (*box, embedding, detection["det_score"],
                         min(original["candidate"], detection["candidate"]), keeper["id"]),
                    )
                if duplicate is not None:
                    conn.execute(
                        "INSERT OR IGNORE INTO rejections(face_id,person_id) "
                        "SELECT ?,person_id FROM rejections WHERE face_id=?",
                        (keeper["id"], duplicate["id"]),
                    )
                    conn.execute("UPDATE people SET cover_face_id=? WHERE cover_face_id=?",
                                 (keeper["id"], duplicate["id"]))
                    conn.execute("DELETE FROM faces WHERE id=?", (duplicate["id"],))
                replacement.replace(target)
                replaced = True
        except Exception:
            if replaced:
                if previous.exists():
                    previous.replace(target)
                else:
                    target.unlink(missing_ok=True)
            raise
    return keeper["id"]

"""Suggest names for unlabeled faces from confirmed ones, and measure accuracy.

Matching is nearest-neighbour against *every* confirmed face of a person (not a
per-person average), so a photo of Grandma at 80 can match her photos at 70
even if her photos at 5 look nothing alike.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass

import numpy as np
from scipy.optimize import linear_sum_assignment

from . import config, keywords

# Cosine similarity at or above which we suggest a name. ArcFace same-person
# pairs are typically > 0.4; tune on real data with `evaluate`.
SUGGEST_THRESHOLD = 0.35
# Lower bar when the photo's own keywords already say who is in it: we only
# have to pick which face is which among a handful of names.
KEYWORD_THRESHOLD = 0.20


def _vecs(rows) -> np.ndarray:
    return np.stack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])


@dataclass
class Gallery:
    face_ids: np.ndarray
    person_ids: np.ndarray
    vecs: np.ndarray

    @classmethod
    def load(cls, conn: sqlite3.Connection) -> "Gallery | None":
        rows = conn.execute(
            "SELECT id, person_id, embedding FROM faces "
            "WHERE status = 'confirmed' AND person_id IS NOT NULL AND embedding IS NOT NULL"
        ).fetchall()
        if not rows:
            return None
        return cls(np.array([r["id"] for r in rows]),
                   np.array([r["person_id"] for r in rows]), _vecs(rows))

    def best_per_person(self, vec: np.ndarray, exclude_face: int | None = None) -> dict[int, float]:
        sims = self.vecs @ vec
        if exclude_face is not None:
            sims = np.where(self.face_ids == exclude_face, -1.0, sims)
        best: dict[int, float] = {}
        for pid, s in zip(self.person_ids.tolist(), sims.tolist()):
            if s > best.get(pid, -1.0):
                best[pid] = s
        return best


def _impossible_people(conn: sqlite3.Connection) -> dict[int, set[int]]:
    """image_id -> people who can't be in it (photo is dated entirely before
    their birth or after their death)."""
    out: dict[int, set[int]] = defaultdict(set)
    rows = conn.execute(
        """SELECT i.id AS image_id, p.id AS person_id
           FROM images i JOIN photos ph ON ph.id = i.photo_id, people p
           WHERE (p.birth_year IS NOT NULL AND ph.date_max IS NOT NULL
                  AND CAST(substr(ph.date_max, 1, 4) AS INTEGER) < p.birth_year)
              OR (p.death_year IS NOT NULL AND ph.date_min IS NOT NULL
                  AND CAST(substr(ph.date_min, 1, 4) AS INTEGER) > p.death_year)"""
    )
    for r in rows:
        out[r["image_id"]].add(r["person_id"])
    return out


def label_from_keywords(conn: sqlite3.Connection) -> int:
    """A photo keyworded with exactly one person that shows exactly one face: that
    face is the person. The name was already confirmed by whoever keyworded the
    photo; we only infer which face it belongs to. Rejections are respected."""
    rows = conn.execute("""
        SELECT i.photo_id, MIN(f.id) AS face_id, COUNT(*) AS n,
               MAX(f.status = 'confirmed') AS has_confirmed
        FROM faces f JOIN images i ON i.id = f.image_id
        WHERE i.role = 'front' AND f.status != 'ignored' AND f.candidate = 0
        GROUP BY i.photo_id HAVING n = 1""").fetchall()
    n = 0
    for r in rows:
        people = keywords.photo_people(conn, r["photo_id"])
        if len(people) != 1 or r["has_confirmed"]:
            continue
        pid = next(iter(people))
        if conn.execute("SELECT 1 FROM rejections WHERE face_id = ? AND person_id = ?",
                        (r["face_id"], pid)).fetchone():
            continue
        conn.execute("UPDATE faces SET person_id = ?, status = 'confirmed', confidence = NULL, "
                     "label_source = 'keyword' WHERE id = ?", (pid, r["face_id"]))
        n += 1
    conn.commit()
    return n


def _suggest(conn, face_id: int, pid: int, sim: float | None, source: str) -> None:
    conn.execute("UPDATE faces SET person_id = ?, confidence = ?, status = 'suggested', "
                 "label_source = ? WHERE id = ?", (pid, sim, source, face_id))


def suggest(conn: sqlite3.Connection, threshold: float | None = None) -> int:
    """Recompute suggestions for all non-confirmed, non-ignored faces.

    Faces in a photo whose keywords name people are matched against those names
    only (one face per name). Other faces are matched against everyone.
    """
    conn.execute("UPDATE faces SET person_id = NULL, confidence = NULL, status = 'unknown', "
                 "label_source = NULL WHERE status = 'suggested'")
    cfg = config.load(conn)
    if threshold is None:
        threshold = cfg["suggest_threshold"]
    if cfg["keyword_autoconfirm"]:
        label_from_keywords(conn)
    gallery = Gallery.load(conn)
    rejected: dict[int, set[int]] = defaultdict(set)
    for r in conn.execute("SELECT face_id, person_id FROM rejections"):
        rejected[r["face_id"]].add(r["person_id"])
    impossible = _impossible_people(conn)

    rows = conn.execute("SELECT f.id, f.image_id, i.photo_id, f.embedding FROM faces f "
                        "JOIN images i ON i.id = f.image_id "
                        "WHERE f.status = 'unknown' AND f.candidate = 0 "
                        "AND f.embedding IS NOT NULL").fetchall()
    by_photo: dict[int, list] = defaultdict(list)
    for r in rows:
        by_photo[r["photo_id"]].append(r)

    n = 0
    for photo_id, faces in by_photo.items():
        named = {x[0] for x in conn.execute(
            "SELECT f.person_id FROM faces f JOIN images i ON i.id = f.image_id "
            "WHERE i.photo_id = ? AND f.status = 'confirmed'", (photo_id,))}
        candidates = sorted(keywords.photo_people(conn, photo_id) - named)
        leftover = faces
        if candidates:
            leftover, n_kw = _match_keyword_people(conn, faces, candidates, gallery, rejected)
            n += n_kw
        if gallery is None:
            continue
        for r in leftover:  # faces the keywords don't account for: match against everyone
            best = gallery.best_per_person(np.frombuffer(r["embedding"], dtype=np.float32))
            for pid in rejected[r["id"]] | impossible[r["image_id"]] | named | set(candidates):
                best.pop(pid, None)
            if best:
                pid, sim = max(best.items(), key=lambda kv: kv[1])
                if sim >= threshold:
                    _suggest(conn, r["id"], pid, sim, "match")
                    n += 1
    conn.commit()
    return n


def _match_keyword_people(conn, faces: list, candidates: list[int], gallery: "Gallery | None",
                          rejected: dict[int, set[int]]) -> tuple[list, int]:
    """Assign a photo's unnamed faces to the people its keywords name.
    Returns (faces left unassigned, suggestions made)."""
    sims = np.full((len(faces), len(candidates)), -1.0)
    if gallery is not None:
        for i, r in enumerate(faces):
            best = gallery.best_per_person(np.frombuffer(r["embedding"], dtype=np.float32))
            for j, pid in enumerate(candidates):
                if pid not in rejected[r["id"]]:
                    sims[i, j] = best.get(pid, -1.0)
    rows, cols = linear_sum_assignment(-sims)
    used_faces, used_people, n = set(), set(), 0
    for i, j in zip(rows, cols):
        if sims[i, j] >= KEYWORD_THRESHOLD:
            _suggest(conn, faces[i]["id"], candidates[j], float(sims[i, j]), "keyword_match")
            used_faces.add(i)
            used_people.add(j)
            n += 1
    left_faces = [i for i in range(len(faces)) if i not in used_faces]
    left_people = [j for j in range(len(candidates)) if j not in used_people]
    # By elimination: one name left and one face left -> probably them. This is how
    # people who never appear alone (no single-face photo) get their first faces.
    if len(left_faces) == 1 and len(left_people) == 1:
        i, j = left_faces[0], left_people[0]
        if candidates[j] not in rejected[faces[i]["id"]]:
            _suggest(conn, faces[i]["id"], candidates[j], None, "elimination")
            return [], n + 1
    return [faces[i] for i in left_faces], n


def evaluate(conn: sqlite3.Connection, threshold: float = SUGGEST_THRESHOLD) -> None:
    """Leave-one-out over confirmed faces: would we have suggested the right name?

    Reported separately for black-and-white (historical) and colour images.
    """
    gallery = Gallery.load(conn)
    if gallery is None:
        print("No confirmed faces yet - label some clusters first.")
        return
    is_bw = {r["id"]: r["is_bw"] for r in conn.execute(
        "SELECT f.id, i.is_bw FROM faces f JOIN images i ON i.id = f.image_id")}
    counts = Counter3()
    for fid, pid, vec in zip(gallery.face_ids, gallery.person_ids, gallery.vecs):
        others = (gallery.person_ids == pid) & (gallery.face_ids != fid)
        if not others.any():
            continue  # only one example of this person - nothing to match against
        best = gallery.best_per_person(vec, exclude_face=int(fid))
        guess, sim = max(best.items(), key=lambda kv: kv[1])
        group = "b&w" if is_bw.get(int(fid)) else "colour"
        if sim < threshold:
            counts.add(group, "no_suggestion")
        elif guess == pid:
            counts.add(group, "correct")
        else:
            counts.add(group, "wrong")
    counts.print()


class Counter3:
    def __init__(self):
        self.c: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def add(self, group: str, outcome: str) -> None:
        self.c[group][outcome] += 1
        self.c["all"][outcome] += 1

    def print(self) -> None:
        print(f"{'group':8} {'faces':>6} {'correct':>8} {'wrong':>6} {'none':>6} {'top-1 acc':>9}")
        for g in ("b&w", "colour", "all"):
            d = self.c.get(g)
            if not d:
                continue
            total = sum(d.values())
            acc = d["correct"] / total if total else 0
            print(f"{g:8} {total:>6} {d['correct']:>8} {d['wrong']:>6} "
                  f"{d['no_suggestion']:>6} {acc:>8.1%}")

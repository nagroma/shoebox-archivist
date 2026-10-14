"""Likely matches for people you have already named, for review next to the clusters.

Clusters group unnamed faces by how they look. This goes the other way round: for each
person, the unnamed faces that look most like the faces already named as them, strongest
first, so one person's faces are confirmed together.

Anchors are a person's *confirmed* faces. A person with none yet (all their faces are
suggestions, e.g. by elimination from keywords) is seeded from those suggested faces and
flagged as a guess: the seeds are shown first so you can check them. Nothing is confirmed
or hidden here; it only orders and groups faces for review.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict

import numpy as np

from . import config, match


def groups(conn: sqlite3.Connection, threshold: float | None = None) -> list[dict]:
    """[{person_id, confirmed, guess, faces: [{face_id, similarity, seed}]}], most
    confirmed faces first. Each unnamed face appears once, under its closest person."""
    if threshold is None:
        threshold = config.get(conn, "neighbour_threshold")
    rows = conn.execute(
        "SELECT f.id, f.status, f.person_id, i.photo_id, f.embedding FROM faces f "
        "JOIN images i ON i.id = f.image_id WHERE f.candidate = 0 AND f.embedding IS NOT NULL "
        "AND f.status IN ('confirmed', 'suggested', 'unknown')").fetchall()
    if not rows:
        return []
    vec = {r["id"]: np.frombuffer(r["embedding"], dtype=np.float32) for r in rows}
    photo = {r["id"]: r["photo_id"] for r in rows}

    confirmed: dict[int, list[int]] = defaultdict(list)
    suggested: dict[int, list[int]] = defaultdict(list)
    for r in rows:
        if r["person_id"] is None:
            continue
        (confirmed if r["status"] == "confirmed" else suggested)[r["person_id"]].append(r["id"])
    anchors = {p: ids for p, ids in confirmed.items()}
    guess = {p for p in suggested if p not in anchors}
    for p in guess:
        anchors[p] = suggested[p]
    if not anchors:
        return []

    rejected: dict[int, set[int]] = defaultdict(set)
    for r in conn.execute("SELECT face_id, person_id FROM rejections"):
        rejected[r["face_id"]].add(r["person_id"])
    impossible = match._impossible_people(conn)
    image_of = {r["id"]: r["image_id"] for r in conn.execute("SELECT id, image_id FROM faces")}

    out: dict[int, dict] = {}
    anchor_set = {f for ids in anchors.values() for f in ids}
    photos_with = {p: {photo[f] for f in ids} for p, ids in anchors.items()}
    for r in rows:
        fid = r["id"]
        if r["status"] == "confirmed" or fid in anchor_set:
            continue
        best_p, best_s = None, threshold
        for p, ids in anchors.items():
            if p in rejected.get(fid, ()) or p in impossible.get(image_of[fid], ()):
                continue
            if r["photo_id"] in photos_with[p]:      # one person is not twice in a photo
                continue
            s = float(max(np.stack([vec[a] for a in ids]) @ vec[fid]))
            if s >= best_s:
                best_p, best_s = p, s
        if best_p is not None:
            g = out.setdefault(best_p, {"person_id": best_p, "confirmed": len(confirmed.get(best_p, [])),
                                        "guess": best_p in guess, "faces": []})
            g["faces"].append({"face_id": fid, "similarity": round(best_s, 3), "seed": False})
    for p in guess:    # the guesses themselves come first, to be checked
        g = out.setdefault(p, {"person_id": p, "confirmed": 0, "guess": True, "faces": []})
        g["faces"] = [{"face_id": f, "similarity": None, "seed": True} for f in suggested[p]] + g["faces"]
    for g in out.values():
        g["faces"].sort(key=lambda f: (not f["seed"], -(f["similarity"] or 0)))
    return sorted((g for g in out.values() if g["faces"]),
                  key=lambda g: (g["guess"], -g["confirmed"], -len(g["faces"])))

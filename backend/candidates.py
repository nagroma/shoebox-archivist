"""Learn from 'Face' / 'Not a face' decisions to sort the Possible faces list.

A possible face (found only by a thorough-scan extra pass) is compared with
  - real faces: every face not flagged as a candidate (verified or found upright), and
  - non-faces: candidates someone marked 'Not a face' (ignored).
score = mean of its K best similarities to real faces - the same to non-faces.
Clearly positive -> 'face', clearly negative -> 'not_face', otherwise unsure.
Nothing is ever hidden or decided automatically; the UI only sorts and pre-selects.
"""
from __future__ import annotations

import sqlite3

import numpy as np

K = 3
MARGIN = 0.05       # |score| below this is "unsure"
MIN_EXAMPLES = 5    # need at least this many real faces AND non-faces before guessing


def _vecs(rows) -> np.ndarray:
    if not rows:
        return np.zeros((0, 512), np.float32)
    return np.stack([np.frombuffer(r["embedding"], np.float32) for r in rows])


def _top_mean(sims: np.ndarray) -> np.ndarray:
    k = min(K, sims.shape[1])
    return np.sort(sims, axis=1)[:, -k:].mean(axis=1)


def score(conn: sqlite3.Connection) -> tuple[dict[int, tuple[float, str | None]], dict]:
    """Returns ({face_id: (score, likely)}, {"faces": n, "non_faces": n, "active": bool})
    for every pending possible face."""
    pending = conn.execute("SELECT id, embedding FROM faces WHERE candidate = 1 "
                           "AND status != 'ignored' AND embedding IS NOT NULL").fetchall()
    pos = conn.execute("SELECT embedding FROM faces WHERE candidate = 0 "
                       "AND embedding IS NOT NULL").fetchall()
    neg = conn.execute("SELECT embedding FROM faces WHERE candidate = 1 "
                       "AND status = 'ignored' AND embedding IS NOT NULL").fetchall()
    info = {"faces": len(pos), "non_faces": len(neg),
            "active": len(pos) >= MIN_EXAMPLES and len(neg) >= MIN_EXAMPLES}
    if not pending or not info["active"]:
        return {r["id"]: (0.0, None) for r in pending}, info
    q = _vecs(pending)
    s = _top_mean(q @ _vecs(pos).T) - _top_mean(q @ _vecs(neg).T)
    out = {}
    for r, v in zip(pending, s.tolist()):
        likely = "face" if v > MARGIN else "not_face" if v < -MARGIN else None
        out[r["id"]] = (round(v, 3), likely)
    return out, info

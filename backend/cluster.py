"""Group unlabeled faces into clusters and render an HTML review report."""
from __future__ import annotations

import html
import os
import sqlite3
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.cluster import HDBSCAN

from . import config


def cluster(conn: sqlite3.Connection, min_cluster_size: int | None = None) -> int:
    """Cluster faces that have no confirmed name. Returns number of clusters.
    min_cluster_size=None uses the value from Settings."""
    if min_cluster_size is None:
        min_cluster_size = config.get(conn, "min_cluster_size")
    rows = conn.execute(
        "SELECT id, embedding FROM faces WHERE status IN ('unknown', 'suggested') "
        "AND candidate = 0 AND embedding IS NOT NULL"
    ).fetchall()
    conn.execute("UPDATE faces SET cluster_id = NULL")
    if len(rows) < min_cluster_size:
        conn.commit()
        return 0
    vecs = np.stack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
    # Embeddings are L2-normalized, so euclidean distance is monotonic in cosine.
    labels = HDBSCAN(min_cluster_size=min_cluster_size, min_samples=2,
                     cluster_selection_method="leaf", copy=True).fit_predict(vecs)
    conn.executemany("UPDATE faces SET cluster_id = ? WHERE id = ?",
                     [(int(l), r["id"]) for l, r in zip(labels, rows)])
    conn.commit()
    return len(set(labels.tolist()) - {-1})


CSS = """
body{font-family:system-ui,sans-serif;margin:16px;background:#fafafa;color:#222}
h2{margin:28px 0 6px;font-size:18px} .meta{color:#666;font-size:13px}
.grid{display:flex;flex-wrap:wrap;gap:6px}
figure{margin:0;width:120px;font-size:11px;text-align:center}
figure img{width:120px;height:120px;object-fit:cover;border-radius:6px;display:block}
figure.sugg img{outline:3px solid #e0a000} figure.conf img{outline:3px solid #2a9d4b}
code{background:#eee;padding:1px 4px;border-radius:3px}
"""


def _figure(r, thumbs_rel: str, title: str = "") -> str:
    cls = {"suggested": "sugg", "confirmed": "conf"}.get(r["status"], "")
    caption = f"#{r['id']}"
    if r["status"] == "suggested":
        conf = f" {r['confidence']:.2f}" if r["confidence"] is not None else " (by elimination)"
        caption += f" {html.escape(r['person'] or '')}?{conf}"
    tip = html.escape(f"{r['path']}{(' — ' + title) if title else ''}")
    return (f'<figure class="{cls}" title="{tip}"><img loading="lazy" '
            f'src="{thumbs_rel}/{r["id"]}.jpg"><figcaption>{caption}</figcaption></figure>')


def report(conn: sqlite3.Connection, out: Path, thumbs: Path) -> None:
    thumbs_rel = Path(os.path.relpath(thumbs, out.parent)).as_posix()
    rows = conn.execute(
        """SELECT f.id, f.status, f.confidence, f.cluster_id, p.name AS person, i.path
           FROM faces f JOIN images i ON i.id = f.image_id
           LEFT JOIN people p ON p.id = f.person_id
           ORDER BY f.id"""
    ).fetchall()

    people: dict[str, list] = defaultdict(list)
    clusters: dict[int, list] = defaultdict(list)
    for r in rows:
        if r["status"] == "confirmed":
            people[r["person"]].append(r)
        elif r["status"] != "ignored" and r["cluster_id"] is not None:
            clusters[r["cluster_id"]].append(r)

    parts = [f"<!doctype html><meta charset=utf-8><title>Face clusters</title><style>{CSS}</style>",
             f"<h1>Face review</h1><p class=meta>{len(rows)} faces · {len(people)} people · "
             f"{len([c for c in clusters if c >= 0])} unnamed clusters. "
             "Name a cluster with <code>pm label --cluster N --name \"Full Name\" "
             "[--exclude id,id]</code>. Orange = suggested, green = confirmed.</p>"]

    for name in sorted(people):
        faces = people[name]
        parts.append(f"<h2>{html.escape(name)} <span class=meta>({len(faces)} confirmed)</span></h2>"
                     f"<div class=grid>{''.join(_figure(r, thumbs_rel) for r in faces)}</div>")

    ordered = sorted((c for c in clusters if c >= 0), key=lambda c: -len(clusters[c]))
    for cid in ordered + ([-1] if -1 in clusters else []):
        faces = clusters[cid]
        names = [r["person"] for r in faces if r["status"] == "suggested"]
        hint = ""
        if names:
            top = max(set(names), key=names.count)
            hint = f" · mostly suggested as <b>{html.escape(top)}</b> ({names.count(top)}/{len(faces)})"
        title = "Unclustered faces" if cid == -1 else f"Cluster {cid}"
        parts.append(f"<h2>{title} <span class=meta>({len(faces)} faces{hint})</span></h2>"
                     f"<div class=grid>{''.join(_figure(r, thumbs_rel) for r in faces)}</div>")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(parts), encoding="utf-8")

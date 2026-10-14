"""User settings, stored in the DB `settings` table so the CLI and the web UI share them."""
from __future__ import annotations

import json
import sqlite3

from . import db

KEY = "config"

# name -> (default, type, description). Order is the order shown in the UI.
FIELDS: dict[str, tuple] = {
    "detection_mode": ("thorough", str, "thorough = every pass on every photo; fast = extra passes only when nothing is found"),
    "pass_contrast": (True, bool, "extra pass on a contrast-enhanced copy (faded prints)"),
    "pass_enlarged": (True, bool, "extra pass at a larger detector size (small faces); thorough mode only"),
    "pass_rotated": (True, bool, "extra passes on rotated copies (tilted or lying-down heads)"),
    "suggest_threshold": (0.35, float, "similarity needed before a name is suggested (higher = fewer, safer suggestions)"),
    "keyword_autoconfirm": (False, bool, "a photo keyworded with one person that shows one face: confirm that face without review (off: it is only suggested)"),
    "min_cluster_size": (3, int, "smallest group of similar unnamed faces shown as a cluster"),
    "neighbour_threshold": (0.30, float, "unnamed faces at least this similar to a named person are listed as likely matches for that person (lower = more, weaker matches)"),
    "cluster_merge_threshold": (0.45, float, "unnamed groups of the same person are merged when their centres are this similar (lower = fewer, bigger clusters; 1 = never merge)"),
    "preselect_non_faces": (True, bool, "pre-select possible faces that look like earlier 'not a face' decisions"),
    "show_enhanced": (True, bool, "show a scanner's colour-corrected copy (FastFoto '_a') instead of the original when a photo has both"),
}
CHOICES = {"detection_mode": ("thorough", "fast")}
LIMITS = {"suggest_threshold": (0.1, 0.9), "min_cluster_size": (2, 20),
          "cluster_merge_threshold": (0.2, 1.0),
          "neighbour_threshold": (0.15, 0.9)}


def defaults() -> dict:
    return {k: v[0] for k, v in FIELDS.items()}


def load(conn: sqlite3.Connection) -> dict:
    """Saved settings over the defaults. Unknown or unreadable values fall back to the default."""
    out = defaults()
    try:
        saved = json.loads(db.get_setting(conn, KEY) or "{}")
    except ValueError:
        saved = {}
    for k, v in saved.items():
        if k in FIELDS:
            try:
                out[k] = _check(k, v)
            except ValueError:
                pass
    return out


def get(conn: sqlite3.Connection, name: str):
    return load(conn)[name]


def _check(name: str, value):
    if name not in FIELDS:
        raise ValueError(f"unknown setting: {name}")
    kind = FIELDS[name][1]
    if kind is bool:
        if not isinstance(value, bool):
            raise ValueError(f"{name} must be true or false")
    elif kind is int:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
            raise ValueError(f"{name} must be a whole number")
        value = int(value)
    elif kind is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be a number")
        value = float(value)
    elif not isinstance(value, str):
        raise ValueError(f"{name} must be text")
    if name in CHOICES and value not in CHOICES[name]:
        raise ValueError(f"{name} must be one of {', '.join(CHOICES[name])}")
    if name in LIMITS:
        lo, hi = LIMITS[name]
        if not lo <= value <= hi:
            raise ValueError(f"{name} must be between {lo} and {hi}")
    return value


def save(conn: sqlite3.Connection, changes: dict) -> dict:
    """Validate and store changes (all or nothing). Returns the full settings."""
    current = load(conn)
    for k, v in changes.items():
        current[k] = _check(k, v)
    stored = {k: v for k, v in current.items() if v != FIELDS[k][0]}  # keep only non-defaults
    db.set_setting(conn, KEY, json.dumps(stored))
    conn.commit()
    return current

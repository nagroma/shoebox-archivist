import numpy as np
import pytest

from backend import candidates, config, db, match


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    yield c
    c.close()


def test_defaults_until_changed(conn):
    assert config.load(conn) == config.defaults()
    cfg = config.save(conn, {"detection_mode": "fast", "min_cluster_size": 4})
    assert cfg["detection_mode"] == "fast" and cfg["min_cluster_size"] == 4
    assert config.load(conn)["suggest_threshold"] == 0.35


@pytest.mark.parametrize("changes", [
    {"detection_mode": "slow"},
    {"min_cluster_size": 1},
    {"min_cluster_size": 2.5},
    {"suggest_threshold": "high"},
    {"keyword_autoconfirm": 1},
    {"no_such_setting": True},
])
def test_bad_values_are_rejected_and_nothing_is_saved(conn, changes):
    with pytest.raises(ValueError):
        config.save(conn, {"pass_rotated": False, **changes})
    assert config.load(conn) == config.defaults()


def test_threshold_comes_from_settings(conn, monkeypatch):
    seen = []
    monkeypatch.setattr(match, "label_from_keywords", lambda c: seen.append("auto"))
    config.save(conn, {"suggest_threshold": 0.5, "keyword_autoconfirm": False})
    match.suggest(conn)
    assert seen == []  # auto-confirm switched off


def _vec(rng, base, noise=0.3):
    v = base + noise * rng.standard_normal(512)
    return (v / np.linalg.norm(v)).astype(np.float32)


def _face(conn, image_id, emb, candidate, status="unknown"):
    return conn.execute(
        "INSERT INTO faces(image_id, x1, y1, x2, y2, embedding, candidate, status) "
        "VALUES (?, 0, 0, 1, 1, ?, ?, ?)", (image_id, emb.tobytes(), candidate, status)).lastrowid


def test_candidates_scored_from_decisions(conn):
    rng = np.random.default_rng(0)
    face_dir, junk_dir = rng.standard_normal(512), rng.standard_normal(512)
    pid = conn.execute("INSERT INTO photos DEFAULT VALUES").lastrowid
    img = conn.execute("INSERT INTO images(photo_id, role, path, sha1) VALUES (?, 'front', 'a.jpg', 'x')",
                       (pid,)).lastrowid
    likely_face = _face(conn, img, _vec(rng, face_dir), 1)
    likely_junk = _face(conn, img, _vec(rng, junk_dir), 1)

    scores, info = candidates.score(conn)
    assert not info["active"] and scores[likely_face] == (0.0, None)  # nothing learned yet

    for _ in range(candidates.MIN_EXAMPLES):
        _face(conn, img, _vec(rng, face_dir), 0)
        _face(conn, img, _vec(rng, junk_dir), 1, "ignored")
    scores, info = candidates.score(conn)
    assert info == {"faces": 5, "non_faces": 5, "active": True}
    assert scores[likely_face][1] == "face"
    assert scores[likely_junk][1] == "not_face"
    assert scores[likely_face][0] > scores[likely_junk][0]

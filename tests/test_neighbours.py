import numpy as np

from backend import db, neighbours


def _vec(*v):
    a = np.array(v, dtype=np.float32)
    return (a / np.linalg.norm(a)).tobytes()


def _lib(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    people = {n: db.get_or_create_person(conn, n) for n in ("Ann", "Bob")}

    def face(photo, vec, status="unknown", person=None, source=None):
        conn.execute("INSERT OR IGNORE INTO photos(id) VALUES (?)", (photo,))
        conn.execute("INSERT OR IGNORE INTO images(id, photo_id, role, path, sha1) VALUES (?, ?, 'front', ?, 'x')",
                     (photo, photo, f"p{photo}.jpg"))
        return conn.execute(
            "INSERT INTO faces(image_id, x1, y1, x2, y2, embedding, status, person_id, label_source) "
            "VALUES (?, 0, 0, 1, 1, ?, ?, ?, ?)", (photo, vec, status, person, source)).lastrowid
    return conn, people, face


def test_unnamed_faces_listed_under_closest_confirmed_person(tmp_path):
    conn, p, face = _lib(tmp_path)
    face(1, _vec(1, 0, 0), "confirmed", p["Ann"])
    face(2, _vec(0, 1, 0), "confirmed", p["Bob"])
    near_ann = face(3, _vec(1, 0.2, 0))
    near_bob = face(4, _vec(0.1, 1, 0))
    face(5, _vec(0, 0, 1))                                   # looks like nobody
    gs = {g["person_id"]: g for g in neighbours.groups(conn, 0.5)}
    assert [f["face_id"] for f in gs[p["Ann"]]["faces"]] == [near_ann]
    assert [f["face_id"] for f in gs[p["Bob"]]["faces"]] == [near_bob]
    assert not gs[p["Ann"]]["guess"] and gs[p["Ann"]]["confirmed"] == 1


def test_rejected_and_same_photo_faces_are_left_out(tmp_path):
    conn, p, face = _lib(tmp_path)
    face(1, _vec(1, 0, 0), "confirmed", p["Ann"])
    rej = face(2, _vec(1, 0.1, 0))
    conn.execute("INSERT INTO rejections(face_id, person_id) VALUES (?, ?)", (rej, p["Ann"]))
    face(1, _vec(1, 0.05, 0))                                 # second face in Ann's own photo
    assert neighbours.groups(conn, 0.5) == []


def test_guess_seeded_group_shows_seeds_first_and_is_flagged(tmp_path):
    conn, p, face = _lib(tmp_path)
    seed = face(1, _vec(1, 0, 0), "suggested", p["Bob"], "elimination")
    other = face(2, _vec(1, 0.1, 0))
    g, = neighbours.groups(conn, 0.5)
    assert g["guess"] and g["confirmed"] == 0
    assert [(f["face_id"], f["seed"]) for f in g["faces"]] == [(seed, True), (other, False)]

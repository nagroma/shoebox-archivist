import pytest
from PIL import Image, ImageDraw

from backend import api, db, ingest, library


@pytest.fixture
def scan(tmp_path, monkeypatch):
    path = tmp_path / "Corrected.jpg"
    image = Image.new("RGB", (100, 100), "red")
    ImageDraw.Draw(image).rectangle((50, 50, 99, 99), fill="blue")
    image.save(path)
    data = library.create(tmp_path, [])
    thumbs = data / "thumbs"
    monkeypatch.setattr(library, "thumbs_dir", lambda: thumbs)
    with db.connect(data / "library.db") as conn:
        ingest.register_images(conn, tmp_path, tmp_path)
        yield conn, conn.execute("SELECT id FROM images").fetchone()[0], path, thumbs


def add_face(conn, image_id, box, *, person=None, embedding=None):
    return conn.execute(
        "INSERT INTO faces(image_id,x1,y1,x2,y2,status,person_id,label_source,embedding) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (image_id, *box, "confirmed" if person else "unknown", person, "user" if person else None, embedding),
    ).lastrowid


def assert_blue_crop(thumbs, face_id):
    with Image.open(thumbs / f"{face_id}.jpg") as img:
        red, _, blue = img.getpixel((80, 80))
    assert blue > red


def test_repair_moves_old_box_and_merges_duplicate_without_losing_decisions(scan):
    conn, image_id, path, thumbs = scan
    person = db.get_or_create_person(conn, "Example Person")
    rejected = db.get_or_create_person(conn, "Other Person")
    stale = add_face(conn, image_id, (.1, .1, .2, .2), person=person)
    new = add_face(conn, image_id, (.8, .8, .9, .9), embedding=b"example")
    conn.execute("UPDATE people SET cover_face_id=? WHERE id=?", (new, person))
    conn.execute("INSERT INTO rejections VALUES (?,?)", (new, rejected))
    conn.commit()
    original = path.read_bytes()

    result = api.repair_face(stale, api.FaceRepairIn(rotate=True), conn)
    assert result["face_id"] == stale
    assert result["revision"]
    kept, = conn.execute("SELECT id,x1,y1,x2,y2,status,person_id,embedding FROM faces")
    assert tuple(kept) == (stale, .8, .8, .9, .9, "confirmed", person, b"example")
    assert tuple(conn.execute("SELECT * FROM rejections").fetchone()) == (stale, rejected)
    assert conn.execute("SELECT cover_face_id FROM people WHERE id=?", (person,)).fetchone()[0] == stale
    assert_blue_crop(thumbs, stale)
    assert path.read_bytes() == original


def test_repair_can_refresh_only_the_thumbnail(scan):
    conn, image_id, _, thumbs = scan
    face = add_face(conn, image_id, (.8, .8, .9, .9))
    api.repair_face(face, api.FaceRepairIn(rotate=False), conn)
    assert tuple(conn.execute("SELECT x1,y1,x2,y2 FROM faces").fetchone()) == (.8, .8, .9, .9)
    assert_blue_crop(thumbs, face)


def test_repair_does_not_merge_different_confirmed_people(scan):
    conn, image_id, _, thumbs = scan
    first = db.get_or_create_person(conn, "Example Person")
    second = db.get_or_create_person(conn, "Other Person")
    stale = add_face(conn, image_id, (.1, .1, .2, .2), person=first)
    add_face(conn, image_id, (.8, .8, .9, .9), person=second)
    with pytest.raises(api.HTTPException, match="different face decisions") as error:
        api.repair_face(stale, api.FaceRepairIn(rotate=True), conn)
    assert error.value.status_code == 409
    assert conn.execute("SELECT COUNT(*) FROM faces WHERE status='confirmed'").fetchone()[0] == 2
    assert not thumbs.exists()

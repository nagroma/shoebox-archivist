from pathlib import Path

import pytest

from backend.ingest import classify, is_ignored


@pytest.mark.parametrize("rel, ignored", [
    ("IMG_0001.JPG", False),
    ("1920s/Smith family.tif", False),
    ("thumbs/f3/f3e4.jpg", True),
    ("Interop/x.jpg", True),
    ("Lightroom/Catalog Previews.lrdata/1/abc.jpg", True),
    (".hidden/a.jpg", True),
    ("@eaDir/a.jpg", True),
    ("album/.DS_Store", True),
])
def test_is_ignored(rel, ignored):
    assert is_ignored(Path(rel)) is ignored


@pytest.mark.parametrize("name, role, key", [
    ("0012.jpg", "front", "0012"),
    ("0012_b.jpg", "back", "0012"),
    ("0012-back.tif", "back", "0012"),
    ("0012_a.jpg", "front", "0012"),
    ("Smith 1923 reverse.jpg", "back", "smith 1923"),
    ("IMG_0023.JPG", "front", "img_0023"),
])
def test_classify(name, role, key):
    r, k = classify(Path("album") / name)
    assert r == role and k.endswith("/" + key)


def _jpg(path, shade):
    from PIL import Image
    Image.new("RGB", (8, 8), (shade, shade, shade)).save(path)


def test_fastfoto_enhanced_copy_is_the_same_photo(tmp_path):
    from backend import db, ingest
    for name, shade in [("IMG_1.jpg", 10), ("IMG_1_a.jpg", 20), ("IMG_1_b.jpg", 30),
                        ("Solo_a.jpg", 40)]:          # a lone _a has no original: it is the front
        _jpg(tmp_path / name, shade)
    conn = db.connect(tmp_path / "t.db")
    ingest.register_images(conn, tmp_path.resolve(), tmp_path.resolve())
    rows = {r["path"]: (r["role"], r["variant"]) for r in conn.execute("SELECT * FROM images")}
    assert rows == {"IMG_1.jpg": ("front", None), "IMG_1_a.jpg": ("other", "enhanced"),
                    "IMG_1_b.jpg": ("back", None), "Solo_a.jpg": ("front", None)}
    assert conn.execute("SELECT COUNT(DISTINCT photo_id) FROM images").fetchone()[0] == 2


def test_merge_enhanced_folds_an_earlier_import(tmp_path):
    from backend import db, ingest
    conn = db.connect(tmp_path / "t.db")
    for n, (path, sha) in enumerate([("IMG_1.jpg", "a"), ("IMG_1_a.jpg", "b")], 1):
        conn.execute("INSERT INTO photos(id) VALUES (?)", (n,))
        conn.execute("INSERT INTO images(photo_id, role, path, sha1) VALUES (?, 'front', ?, ?)",
                     (n, path, sha))
    merged, left = ingest.merge_enhanced(conn, tmp_path)
    assert (merged, left) == (1, [])
    assert conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0] == 1
    assert conn.execute("SELECT photo_id, role, variant FROM images WHERE path = 'IMG_1_a.jpg'"
                        ).fetchone()[:] == (1, "other", "enhanced")

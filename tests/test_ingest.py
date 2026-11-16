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


def test_fastfoto_corrected_copy_stays_separate_until_a_convention_is_saved(tmp_path):
    from backend import db, ingest

    for name, shade in [("IMG_1.jpg", 10), ("IMG_1_a.jpg", 20), ("IMG_1_b.jpg", 30)]:
        _jpg(tmp_path / name, shade)
    with db.connect(tmp_path / "t.db") as conn:
        ingest.register_images(conn, tmp_path, tmp_path)
        rows = {r["path"]: r["photo_id"] for r in conn.execute("SELECT path, photo_id FROM images")}
        assert rows["IMG_1.jpg"] != rows["IMG_1_a.jpg"]

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

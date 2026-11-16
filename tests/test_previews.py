"""Photo previews follow edits to the original and can be rebuilt explicitly."""
import os

from PIL import Image, ImageDraw
import pytest
from starlette.requests import Request

from backend import api, db, ingest, library


def test_preview_reloads_rotated_source_and_can_refresh_both_sizes(tmp_path, monkeypatch):
    source = tmp_path / "Photo.jpg"
    original = Image.new("RGB", (64, 96), "blue")
    ImageDraw.Draw(original).rectangle((0, 0, 63, 47), fill="red")
    original.save(source)
    data = library.create(tmp_path, [])
    monkeypatch.setattr(library, "cache_dir", lambda: data / "cache")

    def upper_color(path):
        with Image.open(path) as preview:
            red, _, blue = preview.getpixel((16, 16))
        return "red" if red > blue else "blue"

    with db.connect(data / "library.db") as conn:
        ingest.register_images(conn, tmp_path, tmp_path)
        image_id = conn.execute("SELECT id FROM images").fetchone()[0]
        request = Request({"type": "http", "headers": []})
        before = api.image(image_id, request, conn=conn)
        assert upper_color(before.path) == "red"

        exif = original.getexif()
        exif[274] = 3
        original.save(source, exif=exif)
        original_bytes = source.read_bytes()
        os.utime(before.path, ns=(1_000_000_000, 1_000_000_000))
        old_validator = Request({"type": "http", "headers": [(b"if-none-match", before.headers["etag"].encode())]})
        after = api.image(image_id, old_validator, conn=conn)
        assert after.status_code == 200
        assert upper_color(after.path) == "blue"
        current_validator = Request({"type": "http", "headers": [(b"if-none-match", after.headers["etag"].encode())]})
        assert api.image(image_id, current_validator, conn=conn).status_code == 304

        for size in api.SIZES:
            cached = data / "cache" / size / f"{image_id}.jpg"
            cached.parent.mkdir(parents=True, exist_ok=True)
            original.save(cached)
            assert upper_color(cached) == "red"
        assert api.refresh_preview(image_id, conn)["revision"]
        assert all(upper_color(data / "cache" / size / f"{image_id}.jpg") == "blue" for size in api.SIZES)
        assert source.read_bytes() == original_bytes


def test_show_in_finder_reveals_requested_scan_variant(tmp_path, monkeypatch):
    name = "Family Album's Photo_a.jpg"
    source = tmp_path / name
    source.touch()
    data = library.create(tmp_path, [])
    monkeypatch.setattr(api.sys, "platform", "darwin")
    commands = []
    monkeypatch.setattr(api.subprocess, "run", lambda command, **_: commands.append(command))
    json_request = Request({"type": "http", "headers": [(b"content-type", b"application/json")]})
    form_request = Request({"type": "http", "headers": [(b"content-type", b"application/x-www-form-urlencoded")]})

    with db.connect(data / "library.db") as conn:
        photo_id = conn.execute("INSERT INTO photos DEFAULT VALUES").lastrowid
        image_id = conn.execute(
            "INSERT INTO images(photo_id,path,sha1,role,variation) VALUES (?,?,?,'front','_a')",
            (photo_id, name, "corrected"),
        ).lastrowid
        conn.execute("INSERT INTO images(photo_id,path,sha1,role) VALUES (?,?,?,'front')",
                     (photo_id, "Photo.jpg", "original"))
        with pytest.raises(api.HTTPException) as exc:
            api.show_in_finder(image_id, form_request, conn)
        assert exc.value.status_code == 415
        assert api.show_in_finder(image_id, json_request, conn) == {"ok": True}
        assert commands == [["/usr/bin/open", "-R", str(source.resolve())]]

        source.unlink()
        with pytest.raises(api.HTTPException) as exc:
            api.show_in_finder(image_id, json_request, conn)
        assert exc.value.status_code == 404
        assert len(commands) == 1

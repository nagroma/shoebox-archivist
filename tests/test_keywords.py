import shutil
from pathlib import Path

import numpy as np
import pytest

from backend import actions, db, keywords, xmp

SAMPLE = Path(__file__).resolve().parent.parent / "photos" / "12_112mm_Rounded_Coarse" / \
    "112mm_Rounded_Coarse_0002_a.jpg"
needs_sample = pytest.mark.skipif(not SAMPLE.exists(), reason="sample photo not present")


def test_parse_vocabulary():
    text = "Attributes\n\tprimary\n\tunknowndate\n[Smith]\n\tJohnSmith\nOther Keywords\n"
    assert keywords.parse_vocabulary(text) == [
        ("Attributes", "primary"), ("Attributes", "unknowndate"), ("Smith", "JohnSmith")]


@pytest.mark.parametrize("raw, shown", [
    ("JohnSmith", "John Smith"), ("JoePBlack", "Joe P Black"),
    ("RobertJonesJr", "Robert Jones Jr"), ("Jimmy Green", "Jimmy Green"),
    ("Delma", "Delma"),
])
def test_display_name(raw, shown):
    assert keywords.display_name(raw) == shown


def test_keyword_name_round_trip():
    assert keywords.keyword_name("John Smith") == "JohnSmith"


def test_bracketed_vocabulary_groups_hold_people(tmp_path):
    vocab = tmp_path / "Keywords.txt"
    vocab.write_text("[Smith]\n\tJohnSmith\n[Scouts]\n\tTroop9\nPlaces\n\tSpringfield\n", encoding="utf-8")
    conn = db.connect(tmp_path / "t.db")
    keywords.load_vocabulary(conn, vocab)
    kinds = dict(conn.execute("SELECT category, kind FROM keywords").fetchall())
    assert kinds == {"Smith": "person", "Scouts": "scouts", "Places": "place"}
    assert keywords.kind_of("Smith", conn) == "person"  # new keywords in the group too
    assert conn.execute("SELECT name FROM people").fetchall()[0][0] == "John Smith"


def test_split_and_kind():
    assert keywords.split("Smith|JohnSmith") == ("Smith", "JohnSmith")
    assert keywords.split("primary") == (None, "primary")
    assert keywords.kind_of("[People]") == "person"
    assert keywords.kind_of("Places") == "place"
    assert keywords.kind_of("Something New") == "other"


@pytest.mark.parametrize("created, tags, edtf", [
    ("1975-05-01T00:00:00Z", {"unknowndate"}, "1975~"),
    ("1975-05-01T00:00:00Z", {"confirmeddate"}, "1975-05-01"),
    ("1975-05-01", set(), "1975-05-01"),
    ("1975", set(), "1975"),
    (None, {"unknowndate"}, None),
])
def test_date_rule(created, tags, edtf):
    assert keywords.date_rule(created, tags) == edtf


def test_same_name_in_two_groups_is_one_person(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    a = keywords.ensure(conn, "People", "AnnBrown")
    b = keywords.ensure(conn, "Parish", "AnnBrown", kind="person")
    pa, pb = (conn.execute("SELECT person_id FROM keywords WHERE id = ?", (k,)).fetchone()[0]
              for k in (a, b))
    assert pa == pb is not None
    assert keywords.ensure(conn, "Attributes", "primary") and \
        conn.execute("SELECT COUNT(*) FROM people").fetchone()[0] == 1


@needs_sample
def test_xmp_add_remove_strip(tmp_path):
    p = tmp_path / "x.jpg"
    shutil.copy(SAMPLE, p)
    before = xmp.read(p)
    assert before.keywords and before.app_added == []
    existing = before.keywords[0]

    assert xmp.add_keywords(p, ["Smith|TomSmith", existing]) == ["Smith|TomSmith"]
    after = xmp.read(p)
    assert "Smith|TomSmith" in after.keywords and "TomSmith" in after.flat
    assert after.app_added == ["Smith|TomSmith"]
    assert after.description == before.description

    # The owner's own keywords are never removed by default
    assert xmp.remove_keywords(p, [existing]) == []
    assert xmp.strip_app_keywords(p) == ["Smith|TomSmith"]
    final = xmp.read(p)
    assert final.keywords == before.keywords and final.flat == before.flat
    assert final.app_added == []


@needs_sample
def test_confirming_a_face_writes_the_keyword(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    shutil.copy(SAMPLE, lib / "a.jpg")
    conn = db.connect(tmp_path / "t.db")
    db.set_setting(conn, "library_root", str(lib))
    photo = conn.execute("INSERT INTO photos DEFAULT VALUES").lastrowid
    img = conn.execute("INSERT INTO images(photo_id, role, path, sha1) VALUES (?, 'front', 'a.jpg', 'x')",
                       (photo,)).lastrowid
    emb = np.zeros(512, dtype=np.float32).tobytes()
    face = conn.execute("INSERT INTO faces(image_id, x1, y1, x2, y2, embedding) VALUES (?, 0, 0, 1, 1, ?)",
                        (img, emb)).lastrowid
    keywords.ensure(conn, "Smith", "TomSmith", kind="person")
    rick = conn.execute("SELECT id FROM people WHERE name = 'Tom Smith'").fetchone()[0]

    actions.assign(conn, [face], rick)
    assert "Smith|TomSmith" in xmp.read(lib / "a.jpg").app_added
    assert keywords.photo_people(conn, photo) == {rick}

    actions.reject(conn, [face])
    assert "Smith|TomSmith" not in xmp.read(lib / "a.jpg").keywords
    assert keywords.photo_people(conn, photo) == set()

    # A new person without a keyword gets 'People|FirstLast'
    pid = db.get_or_create_person(conn, "Ann Example")
    actions.assign(conn, [face], pid)
    assert "People|AnnExample" in xmp.read(lib / "a.jpg").keywords


@needs_sample
def test_write_and_restore_fields(tmp_path):
    p = tmp_path / "x.jpg"
    shutil.copy(SAMPLE, p)
    before = xmp.read(p)
    xmp.write_fields(p, description="Mary and John", date_created="1975", date_edtf="1975~",
                     location="Springfield")
    mid = xmp.read(p)
    assert (mid.description, mid.date_created, mid.date_edtf, mid.location) == \
        ("Mary and John", "1975", "1975~", "Springfield")
    xmp.write_fields(p, description="second edit")  # original stays the first one
    assert set(xmp.restore_fields(p)) == {xmp.DESC, xmp.DATE, xmp.LOC}
    after = xmp.read(p)
    assert (after.description, after.date_created, after.date_edtf, after.location) == \
        (before.description, before.date_created, None, None)


@needs_sample
def test_legacy_iptc_exif_copies_follow_edits(tmp_path):
    import pyexiv2
    p = tmp_path / "x.jpg"
    shutil.copy(SAMPLE, p)

    def legacy():
        with pyexiv2.Image(str(p)) as im:
            i, e = im.read_iptc(), im.read_exif()
        return (i.get(xmp.IPTC_CAPTION), i.get(xmp.IPTC_DATE), i.get(xmp.IPTC_KW),
                e.get(xmp.EXIF_DESC), e.get(xmp.EXIF_DTO))

    before = legacy()
    xmp.write_fields(p, description="New caption", date_created="1948-06", date_edtf="1948-06")
    xmp.add_keywords(p, ["Places|Springfield"])
    cap, date, kws, desc, dto = legacy()
    assert cap == "New caption" and date == "1948-06-01" and "Springfield" in kws
    assert (desc is None) == (before[3] is None) and (dto is None or dto.startswith("1948:06:01"))

    xmp.restore_fields(p)
    xmp.strip_app_keywords(p)
    assert legacy() == before


def test_flat_keyword_matches_existing_ignoring_spaces(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    kid = keywords.ensure(conn, "People", "MaryWhite")
    assert keywords.resolve(conn, "Mary White") == kid
    assert keywords.resolve(conn, "marywhite") == kid
    other = keywords.resolve(conn, "Sunset")
    assert conn.execute("SELECT category FROM keywords WHERE id = ?", (other,)).fetchone()[0] \
        == "Other Keywords"

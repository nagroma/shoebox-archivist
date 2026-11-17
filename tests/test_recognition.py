"""Existing photo keywords seed recognition; only confirmation edits new photos."""
import numpy as np
import pyexiv2
import pytest
from PIL import Image

from backend import actions, config, db, ingest, keywords, match, xmp


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "library.db")
    db.set_setting(c, "library_root", str(tmp_path))
    yield c
    c.close()


def photo(conn, root, filename, *, grouped=(), flat=(), other=()):
    path = root / filename
    Image.new("RGB", (64, 64), (90, 100, 110)).save(path)
    with pyexiv2.Image(str(path)) as im:
        im.modify_xmp({xmp.HS: list(grouped), xmp.SUBJ: list(flat)})
        if other:
            im.modify_iptc({xmp.IPTC_KW: list(other)})
    pid = conn.execute("INSERT INTO photos DEFAULT VALUES").lastrowid
    iid = conn.execute("INSERT INTO images(photo_id, role, path, sha1) "
                       "VALUES (?, 'front', ?, ?)", (pid, filename, filename)).lastrowid
    return pid, iid


def face(conn, iid, direction=0, *, candidate=0):
    vec = np.zeros(512, dtype=np.float32)
    vec[direction] = 1
    return conn.execute("INSERT INTO faces(image_id, x1, y1, x2, y2, embedding, candidate) "
                        "VALUES (?, 0, 0, 1, 1, ?, ?)", (iid, vec.tobytes(), candidate)).lastrowid


def state(conn, fid):
    return tuple(conn.execute("SELECT status, person_id, label_source FROM faces WHERE id = ?",
                              (fid,)).fetchone())


def test_flat_names_seed_before_later_grouped_photo_and_confirm_writes(conn, tmp_path):
    # The identifying person hierarchy is intentionally in the last file read.
    p1, i1 = photo(conn, tmp_path, "first.jpg", flat=["AnnExample", "Sunset"])
    p2, i2 = photo(conn, tmp_path, "second.jpg", other=["ann example"])
    p3, i3 = photo(conn, tmp_path, "new.jpg")
    _, i4 = photo(conn, tmp_path, "last.jpg", grouped=["People|AnnExample"])
    seeds = [face(conn, iid) for iid in (i1, i2, i4)]
    target = face(conn, i3)
    before = {p.name: p.read_bytes() for p in tmp_path.glob("*.jpg")}

    ingest.read_metadata(conn, tmp_path, progress=lambda *args: None)
    pid = conn.execute("SELECT id FROM people WHERE name = 'Ann Example'").fetchone()[0]
    assert keywords.photo_people(conn, p1) == keywords.photo_people(conn, p2) == {pid}
    assert match.suggest(conn) == 1
    assert all(state(conn, fid) == ("confirmed", pid, "keyword") for fid in seeds)
    assert state(conn, target) == ("suggested", pid, "match")
    assert keywords.photo_people(conn, p3) == set()
    assert before == {p.name: p.read_bytes() for p in tmp_path.glob("*.jpg")}
    assert conn.execute("SELECT kind FROM keywords WHERE name = 'Sunset'").fetchone()[0] == "other"

    # Confirm through the same action used by the photo and bulk review interfaces.
    actions.assign(conn, [target], pid)
    assert xmp.read(tmp_path / "new.jpg").app_added == ["People|AnnExample"]
    assert keywords.photo_people(conn, p3) == {pid}
    assert all((tmp_path / filename).read_bytes() == before[filename]
               for filename in ("first.jpg", "second.jpg", "last.jpg"))
    actions.reject(conn, [target])
    assert xmp.read(tmp_path / "new.jpg").keywords == []
    assert match.suggest(conn) == 0
    assert state(conn, target) == ("unknown", None, None)


def test_existing_flat_photo_is_repaired_without_reimport(conn, tmp_path):
    ph, iid = photo(conn, tmp_path, "old.jpg", flat=["AnnExample"])
    flat = keywords.resolve(conn, "AnnExample")
    conn.execute("INSERT INTO photo_keywords VALUES (?, ?, 'file')", (ph, flat))
    fid = face(conn, iid)
    before = (tmp_path / "old.jpg").read_bytes()
    grouped = keywords.ensure(conn, "Who|Family", "AnnExample", kind="person")
    pid = conn.execute("SELECT person_id FROM keywords WHERE id = ?", (grouped,)).fetchone()[0]
    match.suggest(conn)
    assert state(conn, fid) == ("confirmed", pid, "keyword")
    assert conn.execute("SELECT source FROM photo_keywords WHERE keyword_id = ?", (flat,)).fetchone()[0] == "file"
    assert keywords.person_keyword(conn, pid) == grouped
    assert (tmp_path / "old.jpg").read_bytes() == before


def test_keyword_typing_reuses_person(conn):
    kid = keywords.ensure(conn, "People", "AnnExample")
    pid = conn.execute("SELECT person_id FROM keywords WHERE id = ?", (kid,)).fetchone()[0]
    for typed in ("AnnExample", "annexample", "ann example", "Ann Example"):
        assert actions.person_id_for(conn, None, typed) == pid
    conn.execute("INSERT INTO person_names(person_id, name) VALUES (?, 'Ann Other')", (pid,))
    assert actions.person_id_for(conn, None, "AnnOther") == pid
    assert conn.execute("SELECT COUNT(*) FROM people").fetchone()[0] == 1


def test_flat_resolution_prefers_person_over_old_unknown(conn):
    old = keywords.resolve(conn, "Ann Example")
    known = keywords.ensure(conn, "People", "AnnExample")
    assert old != known
    assert keywords.resolve(conn, "annexample") == known


def test_multiple_names_matched_and_elimination_needs_confirmation(conn, tmp_path):
    _, single = photo(conn, tmp_path, "single.jpg", grouped=["People|AnnExample"])
    ph, group = photo(conn, tmp_path, "group.jpg",
                      grouped=["People|AnnExample", "People|BenExample"])
    seed = face(conn, single)
    ann, ben = face(conn, group), face(conn, group, 1)
    ingest.read_metadata(conn, tmp_path, progress=lambda *args: None)
    people = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM people")}
    assert match.suggest(conn) == 2
    assert state(conn, seed) == ("confirmed", people["Ann Example"], "keyword")
    assert state(conn, ann) == ("suggested", people["Ann Example"], "keyword_match")
    assert state(conn, ben) == ("suggested", people["Ben Example"], "elimination")
    assert keywords.photo_people(conn, ph) == set(people.values())
    actions.reject(conn, [ben])
    match.suggest(conn)
    assert state(conn, ben) == ("unknown", None, None)


def test_confirming_first_face_auto_confirms_last_tagged_person(conn, tmp_path):
    from backend import api

    _, iid = photo(conn, tmp_path, "pair.jpg", grouped=["People|AnnExample", "People|BenExample"])
    ann_face, ben_face = face(conn, iid), face(conn, iid, 1)
    ingest.read_metadata(conn, tmp_path, progress=lambda *args: None)
    people = dict(conn.execute("SELECT name, id FROM people"))
    before = (tmp_path / "pair.jpg").read_bytes()

    api.faces_assign(api.AssignIn(face_ids=[ann_face], person_id=people["Ann Example"]), conn)

    assert state(conn, ann_face) == ("confirmed", people["Ann Example"], "user")
    assert state(conn, ben_face) == ("confirmed", people["Ben Example"], "keyword")
    assert (tmp_path / "pair.jpg").read_bytes() == before


@pytest.mark.parametrize("enabled", [True, False])
def test_ignoring_an_extra_detection_rechecks_only_the_affected_photo(conn, tmp_path, enabled):
    from backend import api

    tags = ["People|AnnExample", "Families|ExampleFamily"]
    _, seed = photo(conn, tmp_path, "seed.jpg", grouped=tags)
    _, target = photo(conn, tmp_path, "target.jpg", grouped=tags)
    face(conn, seed)
    remaining, ignored = face(conn, target), face(conn, target, 1)
    ingest.read_metadata(conn, tmp_path, progress=lambda *args: None)
    match.suggest(conn)
    pid = conn.execute("SELECT id FROM people WHERE name='Ann Example'").fetchone()[0]
    assert state(conn, remaining) == ("suggested", pid, "keyword_match")

    _, unrelated = photo(conn, tmp_path, "unrelated.jpg", grouped=tags)
    unrelated_face = face(conn, unrelated)
    ingest.read_metadata(conn, tmp_path, progress=lambda *args: None)
    config.save(conn, {"keyword_autoconfirm": enabled})
    before = (tmp_path / "target.jpg").read_bytes()

    api.faces_ignore(api.FacesIn(face_ids=[ignored]), conn)

    expected = ("confirmed", pid, "keyword") if enabled else ("suggested", pid, "keyword_match")
    assert state(conn, remaining) == expected
    assert state(conn, ignored)[0] == "ignored"
    assert state(conn, unrelated_face) == ("unknown", None, None)
    assert (tmp_path / "target.jpg").read_bytes() == before


@pytest.mark.parametrize("entry", ["startup", "library page"])
@pytest.mark.parametrize("enabled", [True, False])
def test_opening_library_rechecks_saved_keyword_suggestions(tmp_path, monkeypatch, entry, enabled):
    import uvicorn
    from contextlib import closing
    from backend import api, cli, library

    monkeypatch.setenv("PM_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(library, "_current", None)
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: None)
    root = tmp_path / "photos"
    root.mkdir()
    path = library.create(root, [{"name": "People", "kind": "person"}]) / "library.db"
    tags = ["People|AnnExample", "Families|ExampleFamily"]

    with closing(db.connect(path)) as conn:
        _, seed = photo(conn, root, "seed.jpg", grouped=tags)
        _, target = photo(conn, root, "target.jpg", grouped=tags)
        _, other = photo(conn, root, "other.jpg", grouped=tags)
        face(conn, seed)
        remaining, ignored = face(conn, target), face(conn, target, 1)
        unknown = face(conn, other)
        ingest.read_metadata(conn, root, progress=lambda *args: None)
        pid = conn.execute("SELECT id FROM people WHERE name='Ann Example'").fetchone()[0]
        conn.execute("UPDATE faces SET status='suggested', person_id=?, label_source='keyword_match' WHERE id=?",
                     (pid, remaining))
        conn.execute("UPDATE faces SET status='ignored' WHERE id=?", (ignored,))
        config.save(conn, {"keyword_autoconfirm": enabled})
    before = (root / "target.jpg").read_bytes()

    if entry == "startup":
        library.remember(root)
        cli.main(["serve", "--no-browser"])
    else:
        api.library_open(api.FolderIn(folder=str(root)))

    with closing(db.connect(path)) as conn:
        expected = ("confirmed", pid, "keyword") if enabled else ("suggested", pid, "keyword_match")
        assert state(conn, remaining) == expected
        assert state(conn, ignored)[0] == "ignored"
        assert state(conn, unknown) == ("unknown", None, None)
    assert (root / "target.jpg").read_bytes() == before


@pytest.mark.parametrize("condition", ["disabled", "rejected", "automatic-anchor", "extra-face", "extra-tag"])
def test_last_face_auto_confirmation_requires_an_unambiguous_manual_anchor(conn, tmp_path, condition):
    tags = ["People|AnnExample", "People|BenExample"]
    if condition == "extra-tag":
        tags.append("People|OtherPerson")
    _, iid = photo(conn, tmp_path, "pair.jpg", grouped=tags)
    ann_face, ben_face = face(conn, iid), face(conn, iid, 1)
    if condition == "extra-face":
        face(conn, iid, 2)
    ingest.read_metadata(conn, tmp_path, progress=lambda *args: None)
    people = dict(conn.execute("SELECT name, id FROM people"))
    actions.assign(conn, [ann_face], people["Ann Example"])
    if condition == "disabled":
        config.save(conn, {"keyword_autoconfirm": False})
    elif condition == "rejected":
        conn.execute("INSERT INTO rejections VALUES (?, ?)", (ben_face, people["Ben Example"]))
    elif condition == "automatic-anchor":
        conn.execute("UPDATE faces SET label_source='keyword' WHERE id=?", (ann_face,))

    match.suggest(conn)

    assert state(conn, ben_face)[0] != "confirmed"
    if condition in {"disabled", "automatic-anchor"}:
        assert state(conn, ben_face) == ("suggested", people["Ben Example"], "elimination")
    elif condition == "rejected":
        assert state(conn, ben_face) == ("unknown", None, None)


def test_keyword_autoconfirm_can_be_disabled_and_candidates_stay_pending(conn, tmp_path):
    _, iid = photo(conn, tmp_path, "single.jpg", grouped=["People|AnnExample"])
    fid = face(conn, iid)
    pending = face(conn, iid, candidate=1)
    ingest.read_metadata(conn, tmp_path, progress=lambda *args: None)
    config.save(conn, {"keyword_autoconfirm": False})
    assert match.suggest(conn) == 1
    assert state(conn, fid)[::2] == ("suggested", "elimination")
    assert state(conn, pending) == ("unknown", None, None)
    assert xmp.read(tmp_path / "single.jpg").app_added == []


def test_accept_unclustered_guesses_keeps_each_name_and_writes_keywords(conn, tmp_path):
    from backend import api

    _, first = photo(conn, tmp_path, 'first.jpg')
    _, second = photo(conn, tmp_path, 'second.jpg')
    _, third = photo(conn, tmp_path, 'unselected.jpg')
    face_ids = [face(conn, first), face(conn, second, 1), face(conn, third)]
    names = [db.get_or_create_person(conn, name) for name in ('Ann Example', 'Ben Example')]
    conn.executemany("UPDATE faces SET status='suggested',person_id=? WHERE id=?",
                     list(zip([*names, names[0]], face_ids)))
    conn.execute('UPDATE faces SET cluster_id=-1 WHERE id=?', (face_ids[1],))
    conn.commit()
    before = (tmp_path / 'unselected.jpg').read_bytes()
    result = api.faces_accept_guesses(api.AcceptGuessesIn(guesses=[
        api.FaceGuessIn(face_id=fid, person_id=pid) for fid, pid in zip(face_ids, names)
    ]), conn)
    assert result['accepted'] == 2
    assert [state(conn, fid) for fid in face_ids[:2]] == [('confirmed', pid, 'user') for pid in names]
    assert xmp.read(tmp_path / 'first.jpg').app_added == ['People|AnnExample']
    assert xmp.read(tmp_path / 'second.jpg').app_added == ['People|BenExample']
    assert (tmp_path / 'unselected.jpg').read_bytes() == before
    assert state(conn, face_ids[2])[0] != 'confirmed'


@pytest.mark.parametrize('stale', ['changed-name', 'unknown', 'numbered-cluster'])
def test_accept_guesses_rejects_entire_stale_selection(conn, tmp_path, stale):
    _, first = photo(conn, tmp_path, 'first.jpg')
    _, second = photo(conn, tmp_path, 'second.jpg')
    fid, stale_fid = face(conn, first), face(conn, second, 1)
    ann, ben = [db.get_or_create_person(conn, name) for name in ('Ann Example', 'Ben Example')]
    conn.execute("UPDATE faces SET status='suggested',person_id=? WHERE id=?", (ann, fid))
    conn.execute('UPDATE faces SET status=?,person_id=?,cluster_id=? WHERE id=?',
                 ('unknown' if stale == 'unknown' else 'suggested',
                  ann if stale == 'changed-name' else ben,
                  3 if stale == 'numbered-cluster' else None, stale_fid))
    conn.commit()
    before = (tmp_path / 'first.jpg').read_bytes()
    with pytest.raises(ValueError, match='no guesses were accepted'):
        actions.accept_suggestions(conn, [(fid, ann), (stale_fid, ben)])
    assert state(conn, fid) == ('suggested', ann, None)
    assert (tmp_path / 'first.jpg').read_bytes() == before

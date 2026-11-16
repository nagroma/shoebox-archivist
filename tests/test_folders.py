import numpy as np
import pytest
import pyexiv2
from pathlib import Path
from threading import Event
from PIL import Image

from backend import api, cli, db, face_review, faces, folders, ingest, library, match


def _photo(root, relative, color, keyword):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (24, 24), color).save(path)
    with pyexiv2.Image(str(path)) as metadata:
        metadata.modify_xmp({"Xmp.lr.hierarchicalSubject": [keyword]})
    return path


def _names(rows):
    return {row["name"] for row in rows}


def test_folder_picker_offers_icloud_drive_when_present(tmp_path, monkeypatch):
    monkeypatch.setattr(api.sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert "icloud" not in api.fs_list()
    drive = tmp_path / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
    archive = drive / "Photo Archive"
    archive.mkdir(parents=True)

    assert api.fs_list()["icloud"] == str(drive)
    assert api.fs_list(str(drive))["dirs"] == [{"name": archive.name, "path": str(archive)}]


def test_staged_setup_loads_only_root_vocabulary(tmp_path, monkeypatch):
    (tmp_path / "Keywords.txt").write_text("[Names]\n\tAlexLane\n", encoding="utf-8")
    photo = _photo(tmp_path, "Batch/front.jpg", "red", "Subjects|FileOnly")
    original = photo.read_bytes()
    monkeypatch.setattr(library, "scan", lambda *_: pytest.fail("setup read the photo folders"))
    monkeypatch.setattr(api, "_switch_to", lambda _: None)
    monkeypatch.setattr(api, "library_get", lambda: {})
    monkeypatch.setattr(api.JOB, "start", lambda *_: pytest.fail("setup started a scan"))

    inspection = api.library_inspect(api.InspectIn(folder=str(tmp_path), staged=True, preset="blank"))
    assert inspection["keyword_file"] and inspection["facets"][0]["kind"] == "person"
    api.library_create(api.CreateIn(folder=str(tmp_path), staged=True, facets=inspection["facets"]))
    with db.connect(library.data_dir_for(tmp_path) / "library.db") as conn:
        assert not conn.execute("SELECT 1 FROM images").fetchone()
        assert _names(api.keyword_list(True, conn)) == {"AlexLane"}
        assert all(not row["learn"] and not row["identify"] for row in folders.tree(conn)["folders"])
    assert photo.read_bytes() == original


def test_scan_indexes_both_selections_and_only_detects_identify(tmp_path, monkeypatch):
    learn = _photo(tmp_path, "Reference/Old/front.jpg", "red", "Subjects|Reference")
    target = _photo(tmp_path, "New/front.jpg", "blue", "Subjects|NewBatch")
    excluded = _photo(tmp_path, "Other/front.jpg", "green", "Subjects|Excluded")
    originals = {p: p.read_bytes() for p in (learn, target, excluded)}
    monkeypatch.setattr(faces, "active_provider", lambda: "test")
    monkeypatch.setattr(faces, "detect", lambda *_args, **_kwargs: [])
    data = library.create(tmp_path, [], staged=True)
    with db.connect(data / "library.db") as conn:
        api.folder_choose(api.FolderChoice(path="Reference", flag="learn", enabled=True), conn)
        api.folder_choose(api.FolderChoice(path="New", flag="identify", enabled=True), conn)
        with pytest.raises(api.HTTPException) as exc:
            api.folder_choose(api.FolderChoice(path="../Other", flag="learn", enabled=True), conn)
        assert exc.value.status_code == 400

        result = ingest.ingest(conn, tmp_path, data / "thumbs")
        assert (result["added"], result["scanned"]) == (2, 1)
        assert {tuple(row) for row in conn.execute("SELECT path, faces_scanned FROM images")} == {
            ("Reference/Old/front.jpg", 0), ("New/front.jpg", 1)}
        assert _names(api.keyword_list(True, conn)) == {"Reference"}
        assert _names(api.keyword_list(False, conn)) == {"Reference", "NewBatch"}

        (tmp_path / "Keywords.txt").write_text("Subjects\n\tFromRoot\n", encoding="utf-8")
        ingest.ingest(conn, tmp_path, data / "thumbs")
        assert _names(api.keyword_list(True, conn)) == {"FromRoot"}
        assert "Reference" not in api.keywords_export(conn).body.decode()
    assert all(path.read_bytes() == original for path, original in originals.items())


@pytest.mark.parametrize("option, expected", [
    ("--rescan", {"Album/Named.jpg", "Album/Nested/Empty.jpg"}),
    ("--rescan-empty", {"Album/Nested/Empty.jpg"}),
    ("web", {"Album/Named.jpg", "Album/Nested/Empty.jpg"}),
])
def test_face_rescan_visits_only_the_requested_subtree(tmp_path, monkeypatch, option, expected):
    paths = ("Album/Named.jpg", "Album/Nested/Empty.jpg", "Album Extra/Pending.jpg", "Other/Scanned.jpg")
    for path, color in zip(paths, ("red", "blue", "green", "yellow")):
        _photo(tmp_path, path, color, "Subjects|Sample")
    monkeypatch.setattr(faces, "active_provider", lambda: "test")
    monkeypatch.setattr(faces, "detect", lambda *_args, **_kwargs: [])
    data = library.create(tmp_path, [])
    with db.connect(data / "library.db") as conn:
        ingest.ingest(conn, tmp_path, data / "thumbs")
        person = db.get_or_create_person(conn, "Sample Person")
        conn.execute(
            "INSERT INTO faces(image_id,person_id,status,x1,y1,x2,y2) "
            "SELECT id,?,'confirmed',0,0,1,1 FROM images WHERE path='Album/Named.jpg'",
            (person,),
        )
        conn.execute("UPDATE images SET faces_scanned=0 WHERE path='Album Extra/Pending.jpg'")
        conn.commit()

    seen = set()
    load_image = faces.load_image

    def record_image(path):
        seen.add(path.relative_to(tmp_path).as_posix())
        return load_image(path)

    monkeypatch.setattr(faces, "load_image", record_image)
    if option == "web":
        job = api.IngestJob()
        finished = Event()
        run = job._run

        def run_and_signal(*args):
            try:
                run(*args)
            finally:
                finished.set()

        monkeypatch.setattr(job, "_run", run_and_signal)
        monkeypatch.setattr(api, "JOB", job)
        monkeypatch.setattr(api, "_need_library", lambda: data / "library.db")
        monkeypatch.setattr(library, "thumbs_dir", lambda: data / "thumbs")
        with db.connect(data / "library.db") as conn:
            with pytest.raises(api.HTTPException) as exc:
                api.folder_rescan_faces(api.FolderRescan(path="../Other"), conn)
            assert exc.value.status_code == 400
            api.folder_rescan_faces(api.FolderRescan(path="Album"), conn)
        assert finished.wait(5)
        assert job.state["error"] is None
        assert job.state["rescan_folder"] == "Album"
        assert job.state["result"]["scanned"] == len(expected)
    else:
        monkeypatch.setattr(cli, "DATA", data)
        monkeypatch.setattr(cli, "refresh", lambda *_: None)
        cli.main(["--library", str(tmp_path), "ingest", str(tmp_path / "Album"), option])

    assert seen == expected
    with db.connect(data / "library.db") as conn:
        assert conn.execute("SELECT status,person_id FROM faces").fetchone()[:] == ("confirmed", person)
        assert conn.execute("SELECT path FROM images WHERE faces_scanned=0").fetchone()[0] == "Album Extra/Pending.jpg"


def test_learn_and_identify_are_independent_for_existing_faces(tmp_path):
    data = library.create(tmp_path, [], staged=True)
    with db.connect(data / "library.db") as conn:
        person = db.get_or_create_person(conn, "Alex Lane")
        vector = np.array([1, 0], dtype=np.float32).tobytes()
        ids = {}
        for directory in ("Reference", "New", "Other"):
            photo = conn.execute("INSERT INTO photos DEFAULT VALUES").lastrowid
            image = conn.execute("INSERT INTO images(photo_id, path, sha1, role) VALUES (?, ?, ?, 'front')",
                                 (photo, f"{directory}/front.jpg", directory)).lastrowid
            status = "confirmed" if directory == "Reference" else "unknown"
            ids[directory] = conn.execute(
                "INSERT INTO faces(image_id,x1,y1,x2,y2,embedding,status,person_id) VALUES (?,?,?,?,?,?,?,?)",
                (image, 0, 0, 10, 10, vector, status, person if directory == "Reference" else None)
            ).lastrowid
        policy = folders.load(conn)
        policy.choose("Reference", "learn", True)
        policy.choose("New", "identify", True)
        policy.save(conn)

        assert match.suggest(conn) == 1
        selected, _ = face_review.plan(conn)
        assert len(selected) == 1
        assert dict(conn.execute("SELECT id,status FROM faces")) == {
            ids["Reference"]: "confirmed", ids["New"]: "suggested", ids["Other"]: "unknown"}
        policy.choose("Reference", "learn", False)
        policy.save(conn)
        assert match.suggest(conn) == 0
        assert conn.execute("SELECT status FROM faces WHERE id=?", (ids["New"],)).fetchone()[0] == "unknown"


def test_folder_override_only_changes_its_own_flag():
    policy = folders.Policy(default=False, active=True)
    policy.choose("Albums", "learn", True)
    policy.choose("Albums/Skip", "learn", False)
    policy.choose("Albums/Skip/Review", "identify", True)
    assert not policy.image("Albums/Skip/Review/photo.jpg", "learn")
    policy.choose("Albums", "learn", True)
    assert policy.image("Albums/Skip/Review/photo.jpg", "learn")
    assert policy.image("Albums/Skip/Review/photo.jpg", "identify")
    assert not policy.image("Albums/Skip/photo.jpg", "identify")

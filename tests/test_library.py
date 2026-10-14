import shutil
from pathlib import Path

import pytest

from backend import db, keywords, library, xmp

SAMPLE = Path(__file__).resolve().parent.parent / "photos-mt" / "12_112mm_Rounded_Coarse" / \
    "112mm_Rounded_Coarse_0002_a.jpg"
needs_sample = pytest.mark.skipif(not SAMPLE.exists(), reason="sample photo not present")


def test_deep_paths_keep_their_parents():
    assert keywords.split("Places|USA|Texas") == ("Places|USA", "Texas")
    assert keywords.split("[Ashdown]|Ann") == ("Ashdown", "Ann")
    assert keywords.split("Sunset") == (None, "Sunset")
    assert keywords.parse_vocabulary("Places\n\tUSA\n\t\tTexas\n\t\tOhio\n\tCanada\n") == [
        ("Places", "USA"), ("Places|USA", "Texas"), ("Places|USA", "Ohio"), ("Places", "Canada")]


def test_facets_decide_kinds(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    assert keywords.kind_of("Scouts", conn) == "scouts"          # legacy library, no facets
    keywords.set_facets(conn, [{"name": "Who", "kind": "person"}, {"name": "Where", "kind": "place"}])
    assert keywords.kind_of("Who|Smiths", conn) == "person"
    assert keywords.kind_of("Where", conn) == "place"
    assert keywords.kind_of("Scouts", conn) == "other"           # not a facet any more
    assert keywords.default_person_category(conn) == "Who"
    pid = db.get_or_create_person(conn, "Ann Lee")
    kid = keywords.person_keyword(conn, pid)
    assert keywords.path_of(conn, kid) == "Who|AnnLee"


def test_facet_validation_and_protection(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    for bad in ([{"name": "", "kind": "other"}], [{"name": "A|B", "kind": "other"}],
                [{"name": "A", "kind": "bogus"}],
                [{"name": "A", "kind": "other"}, {"name": "a", "kind": "place"}]):
        with pytest.raises(ValueError):
            keywords.set_facets(conn, bad)
    keywords.set_facets(conn, [{"name": "Places", "kind": "place"}])
    keywords.ensure(conn, "Places|USA", "Texas")
    with pytest.raises(ValueError):   # has keywords
        keywords.set_facets(conn, [])
    keywords.set_facets(conn, [{"name": "Places", "kind": "subject"}])
    assert conn.execute("SELECT kind FROM keywords").fetchone()[0] == "subject"
    with pytest.raises(ValueError):   # can't become people
        keywords.set_facets(conn, [{"name": "Places", "kind": "person"}])


def test_export_round_trips_through_parse(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    keywords.set_facets(conn, [{"name": "People", "kind": "person"}, {"name": "Format", "kind": "attribute"}])
    keywords.ensure(conn, "People|Ashdown", "AnnAshdown")
    keywords.ensure(conn, "Places|USA", "Texas")
    text = keywords.export_vocabulary(conn)
    assert text.splitlines()[0] == "Format"          # empty facet is listed
    assert ("People|Ashdown", "AnnAshdown") in keywords.parse_vocabulary(text)
    assert ("Places|USA", "Texas") in keywords.parse_vocabulary(text)


def test_propose_facets_adds_groups_found_in_files():
    found = {"top": {"People": 5, "Pets": 2, "Locations": 1}}
    facets = {f["name"]: f for f in library.propose_facets(found, "family")}
    assert facets["People"]["found"] == 5 and not facets["People"]["from_files"]
    assert (facets["Pets"]["kind"], facets["Pets"]["found"], facets["Pets"]["from_files"]) == ("other", 2, True)
    assert facets["Locations"]["kind"] == "place"
    assert library.propose_facets(None, "blank") == []


def test_create_open_and_reset(tmp_path, monkeypatch):
    monkeypatch.setenv("PM_HOME", str(tmp_path / "home"))
    root = tmp_path / "photos"
    root.mkdir()
    (root / "keep.txt").write_text("x")
    found = {"paths": {"People|Ashdown|AnnAshdown": 2, "Places|Paris": 1}, "top": {}}
    data = library.create(root, [{"name": "People", "kind": "person"}], found, curator="Jane Quill")
    assert data == root.resolve() / ".shoebox" and library.has_library(root)
    with pytest.raises(FileExistsError):
        library.create(root, [])

    conn = db.connect(data / "library.db")
    assert db.get_setting(conn, "library_root") == str(root.resolve())
    paths = {keywords.path_of(conn, r[0]) for r in conn.execute("SELECT id FROM keywords")}
    assert paths == {"People|Ashdown|AnnAshdown", "Places|Paris"}
    assert {r[0] for r in conn.execute("SELECT name FROM people")} == {"Ann Ashdown", "Jane Quill"}
    assert library.get_curator(conn)["name"] == "Jane Quill"
    assert library.set_curator(conn, "") is None and library.get_curator(conn) is None
    conn.close()

    library.remember(root)
    assert library.open_startup() == data
    library.reset(root)
    assert not (root / ".shoebox").exists() and (root / "keep.txt").exists()
    assert library.data_dir() is None and library.last_library() is None


def test_library_follows_a_renamed_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("PM_HOME", str(tmp_path / "home"))
    old = tmp_path / "before"
    old.mkdir()
    library.create(old, [])
    old.rename(tmp_path / "after")
    conn = db.connect(tmp_path / "after" / ".shoebox" / "library.db")
    assert db.library_root(conn) == (tmp_path / "after").resolve()
    library.remember(old)               # stale pointer from before the rename
    assert library.open_startup() is None


def test_alias_resolves_to_the_same_person(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    jen = db.get_or_create_person(conn, "Jennifer Quill")
    conn.execute("INSERT INTO person_names(person_id, name, kind, from_year) VALUES (?, ?, 'married', 2015)",
                 (jen, "Jennifer Driver"))
    assert db.get_or_create_person(conn, "jennifer driver") == jen
    assert conn.execute("SELECT COUNT(*) FROM people").fetchone()[0] == 1


def test_family_labels_from_the_curator(tmp_path):
    from backend import family
    conn = db.connect(tmp_path / "t.db")
    P = {n: db.get_or_create_person(conn, n) for n in
         ["Me", "Mom", "Dad", "Gran", "Aunt", "Cousin", "Sis", "Kid", "Wife", "WifeMom"]}
    for a, b in [("Mom", "Me"), ("Dad", "Me"), ("Mom", "Sis"), ("Gran", "Mom"), ("Gran", "Aunt"),
                 ("Aunt", "Cousin"), ("Me", "Kid"), ("WifeMom", "Wife")]:
        family.add(conn, "parent", P[a], P[b])
    family.add(conn, "partner", P["Wife"], P["Me"])
    lab = family.labels(conn, P["Me"])
    assert {n: lab[P[n]] for n in P} == {
        "Me": "You", "Mom": "Mother/Father", "Dad": "Mother/Father",
        "Gran": "Grandmother/Grandfather", "Aunt": "Aunt/Uncle",
        "Cousin": "1st cousin", "Sis": "Brother/Sister", "Kid": "Son/Daughter", "Wife": "Partner",
        "WifeMom": "Partner's mother/father"}
    assert family._great(2, "Aunt/Uncle") == "Great-great-aunt/great-great-uncle"
    assert family.relatives(conn, P["Me"])["siblings"] == [P["Sis"]]
    with pytest.raises(ValueError):          # a child can't be their parent's parent
        family.add(conn, "parent", P["Kid"], P["Me"])
    family.move(conn, P["Sis"], P["Me"])     # merge: Sis's parent links go to Me, no self-links
    assert family.relatives(conn, P["Me"])["parents"] == sorted([P["Mom"], P["Dad"]])


def test_family_circle_and_photo_filter(tmp_path):
    from backend import api, family
    conn = db.connect(tmp_path / "t.db")
    P = {n: db.get_or_create_person(conn, n) for n in
         ["Me", "Mom", "Gran", "Sis", "Kid", "GrandKid", "Wife", "Cousin", "Aunt"]}
    for a, b in [("Mom", "Me"), ("Mom", "Sis"), ("Gran", "Mom"), ("Gran", "Aunt"), ("Aunt", "Cousin"),
                 ("Me", "Kid"), ("Kid", "GrandKid")]:
        family.add(conn, "parent", P[a], P[b])
    family.add(conn, "partner", P["Me"], P["Wife"])
    one = family.circle(conn, P["Me"], 1)
    assert {n: one[P[n]] for n in ["Me", "Mom", "Sis", "Kid", "Wife"]} == \
        {"Me": 0, "Mom": -1, "Sis": 0, "Kid": 1, "Wife": 0}
    assert P["Gran"] not in one and P["GrandKid"] not in one and P["Cousin"] not in one
    two = family.circle(conn, P["Me"], 2)
    assert two[P["Gran"]] == -2 and two[P["GrandKid"]] == 2 and P["Cousin"] not in two
    t = api.family_tree(P["Me"], 1, conn)
    assert {n["id"] for n in t["nodes"]} == set(one)
    assert all(e["a"] in one and e["b"] in one for e in t["edges"])


def test_branches_follow_descent_and_married_in_partners(tmp_path):
    from backend import actions, family
    conn = db.connect(tmp_path / "t.db")
    P = {n: db.get_or_create_person(conn, n) for n in
         ["Al Quill", "Bea Harcourt", "Jen Quill", "Chris Driver", "Kid Driver", "Loner"]}
    for a, b in [("Al Quill", "Jen Quill"), ("Bea Harcourt", "Jen Quill"),
                 ("Jen Quill", "Kid Driver"), ("Chris Driver", "Kid Driver")]:
        family.add(conn, "parent", P[a], P[b])
    family.add(conn, "partner", P["Al Quill"], P["Bea Harcourt"])
    family.add(conn, "partner", P["Jen Quill"], P["Chris Driver"])
    db.set_setting(conn, "curator_person_id", str(P["Al Quill"]))
    b = family.branches(conn)
    assert b[P["Jen Quill"]] == {"Quill", "Harcourt", "Driver"}   # takes her husband's branch
    assert b[P["Chris Driver"]] == {"Driver"}                        # not in this family tree
    assert b[P["Kid Driver"]] == {"Quill", "Harcourt", "Driver"}
    assert P["Loner"] not in b
    # a photo of Jen + Chris gets all three; nothing is written without apply
    photo = conn.execute("INSERT INTO photos DEFAULT VALUES").lastrowid
    for who in ("Jen Quill", "Chris Driver"):
        kid = keywords.person_keyword(conn, P[who])
        conn.execute("INSERT INTO photo_keywords(photo_id, keyword_id, source) VALUES (?, ?, 'file')", (photo, kid))
    plan = actions.sync_branch_keywords(conn, apply=False)
    assert plan["add"] == 3 and plan["branches"] == {"Quill": 1, "Harcourt": 1, "Driver": 1}
    assert conn.execute("SELECT COUNT(*) FROM photo_keywords").fetchone()[0] == 2


def test_branch_uses_birth_surname(tmp_path):
    from backend import family
    conn = db.connect(tmp_path / "t.db")
    ruth = db.get_or_create_person(conn, "Ruth Quill")       # married name as main name
    conn.execute("INSERT INTO person_names(person_id, name, kind) VALUES (?, 'Ruth Harcourt', 'birth')", (ruth,))
    kid = db.get_or_create_person(conn, "Kid Quill")
    family.add(conn, "parent", ruth, kid)
    assert family.branches(conn)[kid] == {"Harcourt"}


def test_name_shown_depends_on_photo_date():
    from backend import names
    # married name, year known: before it the main (birth) name, from it the married name
    jen = [("Jennifer Driver", "married", 2012)]
    assert names.pick("Jennifer Quill", None, jen, 2011) == "Jennifer Quill"
    assert names.pick("Jennifer Quill", None, jen, 2012) == "Jennifer Driver"
    assert names.pick("Jennifer Quill", None, jen, None) == "Jennifer Driver"   # undated: current name
    # married name with no year is the current name everywhere
    assert names.pick("Jennifer Quill", None, [("Jennifer Driver", "married", None)], 1990) == "Jennifer Driver"
    # main name is the married one (used from 1984), birth name is the alias
    ruth = [("Ruth Harcourt", "birth", None)]
    assert names.pick("Ruth Quill", 1984, ruth, 1960) == "Ruth Harcourt"
    assert names.pick("Ruth Quill", 1984, ruth, 1990) == "Ruth Quill"
    assert names.pick("Ruth Quill", 1984, ruth, None) == "Ruth Quill"
    assert names.pick("Ruth Quill", None, ruth, 1960) == "Ruth Quill"    # no year: nothing to switch on
    assert names.parse_aliases(names.FIELD.join(["A B", "birth", ""])) == [("A B", "birth", None)]


def test_delete_unused_keyword_only(tmp_path, monkeypatch):
    from backend import api
    conn = db.connect(tmp_path / "t.db")
    used = keywords.ensure(conn, "Places", "Paris")
    spare = keywords.ensure(conn, "Places", "Typo")
    photo = conn.execute("INSERT INTO photos DEFAULT VALUES").lastrowid
    conn.execute("INSERT INTO photo_keywords(photo_id, keyword_id, source) VALUES (?, ?, 'file')", (photo, used))
    conn.commit()
    api.keyword_delete(spare, conn)
    with pytest.raises(Exception, match="1 photo"):
        api.keyword_delete(used, conn)
    assert [r[0] for r in conn.execute("SELECT name FROM keywords")] == ["Paris"]


@needs_sample
def test_scan_reads_keywords_without_modifying(tmp_path):
    shutil.copy(SAMPLE, tmp_path / "a.jpg")
    before = (tmp_path / "a.jpg").read_bytes()
    r = library.scan(tmp_path)
    assert r["images"] == 1 and r["with_keywords"] == 1 and r["paths"]
    assert (tmp_path / "a.jpg").read_bytes() == before
    assert set(r["top"]) == {keywords.top_level(k) for k in xmp.read(tmp_path / "a.jpg").keywords}


@needs_sample
def test_deep_keyword_written_back_unchanged(tmp_path):
    from backend import actions
    root = tmp_path / "lib"
    root.mkdir()
    shutil.copy(SAMPLE, root / "a.jpg")
    xmp.add_keywords(root / "a.jpg", ["People|Ashdown|AnnAshdown"])
    conn = db.connect(tmp_path / "t.db")
    db.set_setting(conn, "library_root", str(root))
    photo = conn.execute("INSERT INTO photos DEFAULT VALUES").lastrowid
    conn.execute("INSERT INTO images(photo_id, role, path, sha1) VALUES (?, 'front', 'a.jpg', 'x')", (photo,))
    kid = keywords.resolve(conn, "People|Ashdown|AnnAshdown")
    conn.execute("INSERT INTO photo_keywords(photo_id, keyword_id, source) VALUES (?, ?, 'file')", (photo, kid))
    assert keywords.path_of(conn, kid) == "People|Ashdown|AnnAshdown"
    assert actions.remove_photo_keyword(conn, photo, kid, only_app=False)
    assert "People|Ashdown|AnnAshdown" not in xmp.read(root / "a.jpg").keywords


def test_former_partner(tmp_path):
    from backend import family
    conn = db.connect(tmp_path / "t.db")
    P = {n: db.get_or_create_person(conn, n) for n in ["Me", "Ex", "ExMom", "Wife", "WifeMom"]}
    for a, b in [("ExMom", "Ex"), ("WifeMom", "Wife")]:
        family.add(conn, "parent", P[a], P[b])
    family.add(conn, "partner", P["Me"], P["Ex"])
    family.add(conn, "partner", P["Me"], P["Wife"])
    family.set_ended(conn, P["Me"], P["Ex"], True, 1998)
    lab = family.labels(conn, P["Me"])
    assert lab[P["Ex"]] == "Former partner" and lab[P["Wife"]] == "Partner"
    assert lab[P["WifeMom"]] == "Partner's mother/father" and P["ExMom"] not in lab
    rel = family.relatives(conn, P["Me"])
    assert rel["partners"] == [P["Wife"]] and rel["former_partners"] == [P["Ex"]]
    assert family.end_years(conn, P["Me"]) == {P["Ex"]: 1998}
    assert any(e["ended"] for e in family.edges_among(conn, set(P.values())) if e["kind"] == "partner")
    family.set_ended(conn, P["Ex"], P["Me"], False)          # reconciled
    assert family.relatives(conn, P["Me"])["former_partners"] == []
    with pytest.raises(ValueError):
        family.set_ended(conn, P["Me"], P["ExMom"], True)


@needs_sample
def test_regroup_turns_family_keyword_into_people_and_family(tmp_path):
    from backend import regroup
    photo = tmp_path / "a.jpg"
    shutil.copy(SAMPLE, photo)
    xmp.add_keywords(photo, ["Ashdown|JuliaAshdown"])       # stands in for the owner's keyword
    xmp.write_fields(photo)                          # no-op, keeps the file valid
    before = xmp.read(photo)
    owner = [k for k in before.keywords if k != "Ashdown|JuliaAshdown"]
    # make Ashdown|JuliaAshdown the owner's own: not app-added
    xmp._write(photo, before.keywords, before.flat, [], removed=None)

    conn = db.connect(tmp_path / "t.db")
    db.set_setting(conn, "library_root", str(tmp_path))
    keywords.set_facets(conn, [{"name": "Ashdown", "kind": "other"}])
    conn.execute("INSERT INTO photos(id) VALUES (1)")
    conn.execute("INSERT INTO images(photo_id, path, role, sha1) VALUES (1, 'a.jpg', 'front', 'x')")
    kid = keywords.ensure(conn, "Ashdown", "JuliaAshdown")
    conn.execute("INSERT INTO photo_keywords(photo_id, keyword_id, source) VALUES (1, ?, 'file')", (kid,))
    conn.commit()

    p = regroup.plan(conn, ["Ashdown"])
    assert p["photos"] == 1 and p["groups"][0]["people"][0]["to"] == "People|JuliaAshdown"
    assert xmp.read(photo).keywords.count("Ashdown|JuliaAshdown") == 1   # plan changed nothing

    r = regroup.apply(conn, ["Ashdown"])
    assert r["converted"] == 1 and r["failed"] == 0
    got = xmp.read(photo)
    assert "People|JuliaAshdown" in got.keywords and "Family|Ashdown" in got.keywords
    assert "Ashdown|JuliaAshdown" not in got.keywords and "Ashdown|JuliaAshdown" in got.removed
    assert {f["name"] for f in keywords.get_facets(conn)} == {"People", "Family"}
    assert conn.execute("SELECT person_id FROM keywords WHERE name = 'JuliaAshdown'").fetchone()[0]
    assert set(owner) <= set(got.keywords)

    xmp.strip_app_keywords(photo)                     # undo
    back = xmp.read(photo)
    assert "Ashdown|JuliaAshdown" in back.keywords and "People|JuliaAshdown" not in back.keywords
    assert back.removed == []


def test_marks_structure_new_person_and_reuse(tmp_path):
    """Several person facets: new people go to People, and an existing Ashdown|X is reused."""
    conn = db.connect(tmp_path / "t.db")
    keywords.set_facets(conn, [{"name": "Ashdown", "kind": "person"}, {"name": "Marlowe", "kind": "person"},
                               {"name": "People", "kind": "person"}])
    assert keywords.default_person_category(conn) == "People"
    hoyt = keywords.ensure(conn, "Ashdown", "JuliaAshdown")
    conn.execute("UPDATE keywords SET kind = 'person' WHERE id = ?", (hoyt,))
    lois = db.get_or_create_person(conn, "Julia Ashdown")
    assert keywords.person_keyword(conn, lois) == hoyt
    assert keywords.path_of(conn, hoyt) == "Ashdown|JuliaAshdown"
    stranger = db.get_or_create_person(conn, "Pat Jones")
    assert keywords.path_of(conn, keywords.person_keyword(conn, stranger)) == "People|PatJones"
    assert conn.execute("SELECT COUNT(*) FROM keywords WHERE name = 'JuliaAshdown'").fetchone()[0] == 1


def test_family_category_reuses_existing_group(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    assert keywords.family_category(conn) == "Family"
    keywords.set_facets(conn, [{"name": "Families", "kind": "other"}])
    assert keywords.family_category(conn) == "Families"


def test_propose_facets_from_files_only(tmp_path):
    from backend import library
    paths = {"Ashdown|JuliaAshdown": 4, "Ashdown|NoahWren": 16, "Ashdown|PerrySkye": 5, "Ashdown|OrlaWren": 3,
             "Ashdown|PipWren": 1, "Events|Wedding": 2, "Places|USA|Ohio": 3}
    found = {"paths": paths, "top": {"Ashdown": 29, "Events": 2, "Places": 3}}
    assert library.default_preset(found) == "files"
    assert library.default_preset({"top": {}}) == "family"
    facets = {f["name"]: f for f in library.propose_facets(found, "files")}
    assert set(facets) == {"Ashdown", "Events", "Places"}            # nothing invented
    assert facets["Ashdown"]["looks_like_people"] and facets["Ashdown"]["kind"] == "other"
    assert facets["Ashdown"]["samples"][0] == "NoahWren"
    assert not facets["Events"]["looks_like_people"] and facets["Events"]["kind"] == "event"
    assert facets["Places"]["samples"] == ["Ohio"]


def test_unmapped_groups_adopt_and_leave(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    assert keywords.unmapped_groups(conn) == []                    # no facets: nothing to compare
    keywords.set_facets(conn, [{"name": "People", "kind": "person"}])
    for n in ("AnnLee", "BobLee", "CyLee", "DotLee", "EdLee"):
        keywords.ensure(conn, "Lee", n)
    keywords.ensure(conn, "Pets", "Rex")
    keywords.ensure(conn, "People", "Zed")
    found = {g["name"]: g for g in keywords.unmapped_groups(conn)}
    assert set(found) == {"Lee", "Pets"} and found["Lee"]["looks_like_people"]
    keywords.dismiss_group(conn, "pets")
    assert [g["name"] for g in keywords.unmapped_groups(conn)] == ["Lee"]
    keywords.adopt_group(conn, "lee", "person")
    assert keywords.unmapped_groups(conn) == []
    assert keywords.kind_of("Lee|AnnLee", conn) == "person"
    assert conn.execute("SELECT COUNT(*) FROM keywords WHERE category = 'Lee' AND person_id IS NOT NULL"
                        ).fetchone()[0] == 5
    assert keywords.path_of(conn, keywords.ensure(conn, "Lee", "AnnLee")) == "Lee|AnnLee"   # path unchanged


def test_merge_similar_clusters():
    import numpy as np
    from backend import cluster
    rng = np.random.default_rng(1)
    def blob(center, n):
        v = np.array(center, dtype=np.float32) + rng.normal(0, 0.05, (n, 3)).astype(np.float32)
        return v / np.linalg.norm(v, axis=1, keepdims=True)
    # one person in two tight groups (a, b), another person far away (c), plus noise
    vecs = np.vstack([blob([1, 0.2, 0], 5), blob([1, 0.5, 0], 5), blob([0, 0, 1], 5), blob([0, 1, 0], 1)])
    labels = np.array([0] * 5 + [1] * 5 + [2] * 5 + [-1])
    out = cluster.merge_similar(vecs, labels, 0.8)
    assert len(set(out[:10])) == 1 and out[10] != out[0] and out[-1] == -1
    assert list(cluster.merge_similar(vecs, labels, 1.0)) == list(labels)

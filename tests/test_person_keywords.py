"""Keyword choices and file round-trips use generated photos, never the collection."""
import pyexiv2
import pytest
from PIL import Image

from backend import actions, db, keywords, xmp


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / 'test.db')
    db.set_setting(c, 'library_root', str(tmp_path))
    keywords.set_facets(c, [{'name': 'People', 'kind': 'person'},
                           {'name': 'Community', 'kind': 'person'},
                           {'name': 'Places', 'kind': 'place'}])
    yield c
    c.close()


def test_confirm_combination_and_undo_preserve_owner_keywords(conn, tmp_path):
    path = tmp_path / 'photo.jpg'
    Image.new('RGB', (32, 32)).save(path)
    with pyexiv2.Image(str(path)) as im:
        im.modify_xmp({xmp.HS: ['Places|Home'], xmp.SUBJ: ['Home', 'AnnSmith']})
        im.modify_iptc({xmp.IPTC_KW: ['Home', 'AnnSmith']})
    pid = db.get_or_create_person(conn, 'Ann Smith')
    first = keywords.attach_person_keyword(conn, pid, 'People', 'AnnSmith')
    second = keywords.attach_person_keyword(conn, pid, 'Community|Choir', 'AnnSmith')
    keywords.set_person_keywords(conn, pid, [first, second])
    photo = conn.execute('INSERT INTO photos DEFAULT VALUES').lastrowid
    image = conn.execute("INSERT INTO images(photo_id,role,path,sha1) VALUES (?, 'front', 'photo.jpg', 'x')", (photo,)).lastrowid
    face = conn.execute('INSERT INTO faces(image_id,x1,y1,x2,y2) VALUES (?,0,0,1,1)', (image,)).lastrowid
    actions.assign(conn, [face], pid)
    info = xmp.read(path)
    assert info.keywords == ['Places|Home', 'People|AnnSmith', 'Community|Choir|AnnSmith']
    with pyexiv2.Image(str(path)) as im:
        assert im.read_iptc()[xmp.IPTC_KW] == ['Home', 'AnnSmith']
    actions.reject(conn, [face])
    assert xmp.read(path).keywords == ['Places|Home']
    assert xmp.read(path).flat == ['Home', 'AnnSmith']
    with pyexiv2.Image(str(path)) as im:
        assert im.read_iptc()[xmp.IPTC_KW] == ['Home', 'AnnSmith']


def test_creates_iptc_and_strips_only_added_keywords(tmp_path):
    path = tmp_path / 'blank.jpg'
    Image.new('RGB', (32, 32)).save(path)
    xmp.add_keywords(path, ['People|AnnSmith', 'Community|AnnSmith'])
    with pyexiv2.Image(str(path)) as im:
        assert im.read_iptc()[xmp.IPTC_KW] == ['AnnSmith']
    xmp.remove_keywords(path, ['People|AnnSmith'])
    with pyexiv2.Image(str(path)) as im:
        assert im.read_iptc()[xmp.IPTC_KW] == ['AnnSmith']
    xmp.strip_app_keywords(path)
    with pyexiv2.Image(str(path)) as im:
        assert not im.read_iptc().get(xmp.IPTC_KW)
    assert not xmp.read(path).keywords


def test_exact_spelling_persistence_and_choice_validation(conn, tmp_path):
    pid = db.get_or_create_person(conn, 'Ann McDonald')
    kid = keywords.attach_person_keyword(conn, pid, 'People|Friends', 'AnnMcDonald')
    keywords.set_person_keywords(conn, pid, [kid])
    conn.commit()
    with db.connect(tmp_path / 'test.db') as reopened:
        assert keywords.person_keywords(reopened, pid) == [kid]
        assert keywords.path_of(reopened, kid) == 'People|Friends|AnnMcDonald'
    other = db.get_or_create_person(conn, 'Other Person')
    with pytest.raises(ValueError):
        keywords.attach_person_keyword(conn, other, 'People|Friends', 'AnnMcDonald')
    with pytest.raises(ValueError):
        keywords.set_person_keywords(conn, other, [kid])
    with pytest.raises(ValueError):
        keywords.set_person_keywords(conn, pid, [])
    with pytest.raises(ValueError):
        keywords.attach_person_keyword(conn, pid, 'Places', 'AnnMcDonald')
    with pytest.raises(ValueError):
        keywords.attach_person_keyword(conn, pid, 'People||Friends', 'AnnMcDonald')


def test_keyword_preference_does_not_rewrite_photos(conn, tmp_path):
    path = tmp_path / 'owned.jpg'
    Image.new('RGB', (32, 32)).save(path)
    xmp.add_keywords(path, ['People|AnnSmith'])
    before = path.read_bytes()
    pid = db.get_or_create_person(conn, 'Ann Smith')
    kid = keywords.attach_person_keyword(conn, pid, 'Community', 'AnnSmith')
    keywords.set_person_keywords(conn, pid, [kid])
    conn.commit()
    assert path.read_bytes() == before


def test_explicit_removal_can_remove_owner_iptc(tmp_path):
    path = tmp_path / 'owner.jpg'
    Image.new('RGB', (32, 32)).save(path)
    with pyexiv2.Image(str(path)) as im:
        im.modify_xmp({xmp.HS: ['People|AnnSmith'], xmp.SUBJ: ['AnnSmith']})
        im.modify_iptc({xmp.IPTC_KW: ['AnnSmith']})
    xmp.remove_keywords(path, ['People|AnnSmith'], only_app_added=False)
    with pyexiv2.Image(str(path)) as im:
        assert not im.read_iptc().get(xmp.IPTC_KW)
    assert not xmp.read(path).flat


def test_api_creates_and_selects_exact_keyword_without_writing_files(conn):
    from backend import api
    from fastapi import HTTPException
    p = api.person_create(api.PersonCreateIn(name='Ann Smith', keyword_category='People',
                                             keyword_name='AnnSmith'), conn)
    assert p['name'] == 'Ann Smith'
    assert p['keyword_ids'] == [p['keywords'][0]['id']]
    p = api.person_keywords_update(p['id'], api.PersonKeywordsIn(
        keyword_ids=p['keyword_ids'], category='Community', name='AnnSmith'), conn)
    assert len(p['keyword_ids']) == 2
    summary = next(r for r in api.people(conn) if r['id'] == p['id'])
    assert summary['keyword_paths'] == ['Community|AnnSmith', 'People|AnnSmith']
    with pytest.raises(HTTPException):
        api.person_keywords_update(p['id'], api.PersonKeywordsIn(keyword_ids=[99999]), conn)
    assert len(api.person(p['id'], conn)['keyword_ids']) == 2
    with pytest.raises(HTTPException):
        api.person_create(api.PersonCreateIn(name='New Person', keyword_category='Places',
                                             keyword_name='NewPerson'), conn)
    assert not conn.execute("SELECT 1 FROM people WHERE name = 'New Person'").fetchone()


def test_merge_keeps_destination_keyword_choices(conn):
    src = db.get_or_create_person(conn, 'Ann Smith')
    dst = db.get_or_create_person(conn, 'Anne Smith')
    a = keywords.attach_person_keyword(conn, src, 'People', 'AnnSmith')
    b = keywords.attach_person_keyword(conn, dst, 'Community', 'AnneSmith')
    keywords.set_person_keywords(conn, src, [a])
    keywords.set_person_keywords(conn, dst, [b])
    actions.merge_people(conn, src, dst)
    assert keywords.person_keywords(conn, dst) == [b]
    assert conn.execute('SELECT person_id FROM keywords WHERE id = ?', (a,)).fetchone()[0] == dst

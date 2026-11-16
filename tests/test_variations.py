"""Generated photo files exercise grouping, metadata scopes and safe review end to end."""
import copy
import json

import numpy as np
import pyexiv2
import pytest
from PIL import Image

from backend import actions, api, db, ingest, keywords, sharing, variations, xmp


@pytest.fixture
def lib(tmp_path):
    conn = db.connect(tmp_path / 'library.db')
    db.set_setting(conn, 'library_root', str(tmp_path))
    keywords.set_facets(conn, [{'name': 'People', 'kind': 'person'},
                              {'name': 'Attributes', 'kind': 'attribute'}])
    yield conn, tmp_path
    conn.close()


def config(**changes):
    result = copy.deepcopy(variations.DEFAULT)
    result.update(enabled=True, **changes)
    return result


def photo(root, name, kws=()):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    color = sum(name.encode()) % 200
    Image.new('RGB', (32, 32), (color, color // 2, 25)).save(path)
    if kws:
        with pyexiv2.Image(str(path)) as im:
            im.modify_xmp({xmp.HS: list(kws), xmp.SUBJ: list(dict.fromkeys(xmp.leaf(k) for k in kws))})
            im.modify_iptc({xmp.IPTC_KW: list(dict.fromkeys(xmp.leaf(k) for k in kws))})
    return path


def register(conn, root):
    ingest.register_images(conn, root, root)
    ingest.read_metadata(conn, root)
    sharing.inventory(conn)


def group(conn, cfg=None, overrides=None):
    cfg = cfg or config()
    p = variations.preview(conn, cfg, overrides)
    variations.apply(conn, cfg, p['token'], overrides)
    return conn.execute('SELECT photo_id FROM images ORDER BY is_primary DESC,id').fetchone()[0]


def kid(conn, path):
    cat, name = path.rsplit('|', 1)
    return keywords.ensure(conn, cat, name)


def make_face(conn, image_id, person_id=None):
    v = np.zeros(512, dtype=np.float32); v[0] = 1
    return conn.execute('INSERT INTO faces(image_id,x1,y1,x2,y2,embedding,status,person_id) '
                        'VALUES (?,0,0,1,1,?,?,?)',
                        (image_id, v.tobytes(), 'confirmed' if person_id else 'unknown', person_id)).lastrowid


def trio(conn, root):
    paths = [photo(root, 'Series_0005.jpg', ['People|AnnSmith']),
             photo(root, 'Series_0005_a.jpg', ['Attributes|portrait']),
             photo(root, 'Series_0005_b.jpg', ['Attributes|hide'])]
    register(conn, root)
    return paths


def test_preview_grouping_preserves_files_faces_and_back_keywords(lib):
    conn, root = lib
    paths = trio(conn, root)
    person = conn.execute("SELECT id FROM people WHERE name='Ann Smith'").fetchone()[0]
    image = conn.execute("SELECT id FROM images WHERE path='Series_0005.jpg'").fetchone()[0]
    fid = make_face(conn, image, person)
    conn.commit()
    before = {p: p.read_bytes() for p in paths}
    p = variations.preview(conn, config(pattern='serial'))
    assert len(p['groups']) == 1
    assert len(p['groups'][0]['members']) == 3
    assert p['groups'][0]['metadata_conflicts'] == []
    assert {path: path.read_bytes() for path in paths} == before
    pid = group(conn, config(pattern='serial'))
    assert conn.execute('SELECT COUNT(*) FROM photos').fetchone()[0] == 1
    assert conn.execute('SELECT image_id,status FROM faces WHERE id=?', (fid,)).fetchone()[:] == (image, 'confirmed')
    assert {path: path.read_bytes() for path in paths} == before
    images = [dict(r) for r in conn.execute('SELECT * FROM images WHERE photo_id=?', (pid,))]
    assert next(i for i in images if i['is_primary'])['path'].endswith('_a.jpg')
    assert sum(i['recognition_enabled'] for i in images) == 1
    assert len(sharing.review(conn)['differences']) == 6  # all three keyword kinds are shared by default
    assert xmp.read(paths[2]).keywords == ['Attributes|hide']
    detail = api.photo(pid, conn)
    assert len(detail['images']) == 3
    assert detail['images'][0]['is_primary'] == 1
    assert set(k['name'] for k in detail['keywords']) == {'AnnSmith', 'portrait', 'hide'}


def test_suffix_meanings_and_roles_can_be_reversed(lib):
    conn, root = lib
    trio(conn, root)
    cfg = config(preferred='_b', recognition='')
    cfg['types'][1].update(role='back', label='Reverse scan')
    cfg['types'][2].update(role='front', label='Enhanced')
    pid = group(conn, cfg)
    rows = {r['variation']: dict(r) for r in conn.execute('SELECT * FROM images WHERE photo_id=?', (pid,))}
    assert rows['_a']['role'] == 'back'
    assert rows['_b']['is_primary'] == 1
    assert rows['']['recognition_enabled'] == 1


def test_serial_keeps_full_prefix_folder_and_unknown_variants_separate():
    cfg = config(pattern='serial')
    a = variations.classify('one/36_Topic_0005_a.jpg', cfg)
    assert a['key'] == 'one/36_topic_0005'
    assert a['suffix'] == '_a'
    assert variations.classify('two/36_Topic_0005_a.jpg', cfg)['key'] != a['key']
    assert variations.classify('one/37_Topic_0005_a.jpg', cfg)['key'] != a['key']
    assert variations.classify('one/36_Topic_0005_z.jpg', cfg)['issue']
    assert variations.classify('one/no_number.jpg', cfg)['issue']
    assert variations.classify('one/36_Topic_0005_a.tif', cfg)['key'] == a['key']


def test_selected_suffix_does_not_include_future_types_but_all_does(lib):
    conn, root = lib
    trio(conn, root)
    pid = group(conn)
    person = kid(conn, 'People|AnnSmith')
    sharing.save(conn, {'rules': [{'target': 'hierarchy', 'path': 'People',
                                  'scope': {'mode': 'selected', 'suffixes': ['', '_a']}}]})
    r = sharing.review(conn)
    assert [d['path'] for d in r['differences'] if d['keyword_id'] == person] == ['Series_0005_a.jpg']
    new = photo(root, 'Series_0005_c.jpg')
    register(conn, root)
    cfg = config(); cfg['types'].append({'suffix': '_c', 'label': 'Extra scan', 'role': 'other'})
    pid = group(conn, cfg)
    assert not any(d['path'] == new.name and d['keyword_id'] == person for d in sharing.review(conn)['differences'])
    sharing.save(conn, {'rules': [{'target': 'hierarchy', 'path': 'People', 'scope': {'mode': 'all'}}]})
    assert any(d['path'] == new.name and d['keyword_id'] == person for d in sharing.review(conn)['differences'])


def test_rule_precedence_ask_and_photo_override(lib):
    conn, root = lib
    trio(conn, root)
    pid = group(conn)
    portrait = kid(conn, 'Attributes|portrait')
    hide = kid(conn, 'Attributes|hide')
    sharing.save(conn, {'rules': [
        {'target': 'hierarchy', 'path': 'Attributes', 'scope': {'mode': 'ask'}},
        {'target': 'keyword', 'path': 'Attributes|hide', 'scope': {'mode': 'backs'}},
    ]})
    r = sharing.review(conn)
    assert {c['keyword_id'] for c in r['choices']} == {portrait}
    assert not [d for d in r['differences'] if d['keyword_id'] == hide]
    sharing.set_photo_scope(conn, pid, portrait, {'mode': 'all'})
    r = sharing.review(conn)
    assert not r['choices']
    assert len([d for d in r['differences'] if d['keyword_id'] == portrait]) == 2
    sharing.set_photo_scope(conn, pid, portrait, None)
    assert sharing.review(conn)['choices']


def test_face_confirm_shares_keywords_and_preserves_exceptions(lib):
    conn, root = lib
    paths = trio(conn, root)
    pid = group(conn)
    person = conn.execute("SELECT id FROM people WHERE name='Ann Smith'").fetchone()[0]
    person_kid = kid(conn, 'People|AnnSmith')
    primary = conn.execute('SELECT id FROM images WHERE is_primary=1').fetchone()[0]
    back = conn.execute("SELECT id FROM images WHERE role='back'").fetchone()[0]
    sharing.exception(conn, back, person_kid, False)
    fid = make_face(conn, primary)
    actions.assign(conn, [fid], person)
    assert 'People|AnnSmith' in xmp.read(paths[0]).keywords
    assert 'People|AnnSmith' in xmp.read(paths[1]).keywords
    assert 'People|AnnSmith' not in xmp.read(paths[2]).keywords
    assert not [d for d in sharing.review(conn)['differences'] if d['keyword_id'] == person_kid]
    sharing.exception(conn, back, person_kid, None)
    assert len([d for d in sharing.review(conn)['differences'] if d['keyword_id'] == person_kid]) == 1


def test_review_owner_removal_requires_explicit_confirmation_and_is_undoable(lib):
    conn, root = lib
    paths = trio(conn, root)
    pid = group(conn)
    sharing.save(conn, {'rules': [{'target': 'hierarchy', 'path': 'People', 'scope': {'mode': 'backs'}}]})
    r = sharing.review(conn)
    remove = next(d for d in r['differences'] if d['action'] == 'remove')
    before = paths[0].read_bytes()
    result = sharing.apply_review(conn, [{'id': remove['id']}])
    assert result['errors'] and paths[0].read_bytes() == before
    result = sharing.apply_review(conn, [{'id': remove['id'], 'allow_owner_removal': True}])
    assert not result['errors']
    assert 'People|AnnSmith' not in xmp.read(paths[0]).keywords
    xmp.strip_app_keywords(paths[0]); xmp.restore_fields(paths[0])
    assert xmp.read(paths[0]).keywords == ['People|AnnSmith']
    with pyexiv2.Image(str(paths[0])) as im:
        assert im.read_iptc()[xmp.IPTC_KW] == ['AnnSmith']


def test_import_late_version_checks_without_changing_metadata(lib, monkeypatch):
    conn, root = lib
    photo(root, 'Batch_0001.jpg', ['People|AnnSmith'])
    photo(root, 'Batch_0001_a.jpg', ['People|AnnSmith'])
    register(conn, root)
    group(conn)
    new = photo(root, 'Batch_0001_b.jpg')
    before = new.read_bytes()
    monkeypatch.setattr(ingest, 'scan_faces', lambda *a, **kw: (0, 0))
    result = ingest.ingest(conn, root, root / 'thumbs')
    assert result['keyword_differences'] == 1
    assert new.read_bytes() == before
    assert conn.execute('SELECT COUNT(*) FROM photos').fetchone()[0] == 1
    r = sharing.review(conn)
    applied = sharing.apply_review(conn, [{'id': d['id']} for d in r['differences']])
    assert not applied['errors']
    assert xmp.read(new).keywords == ['People|AnnSmith']
    with pyexiv2.Image(str(new)) as im:
        assert im.read_iptc()[xmp.IPTC_KW] == ['AnnSmith']


def test_manual_separation_and_regroup_preserve_faces_and_scope(lib):
    conn, root = lib
    trio(conn, root)
    pid = group(conn)
    primary = conn.execute('SELECT id FROM images WHERE is_primary=1').fetchone()[0]
    fid = make_face(conn, primary)
    person = kid(conn, 'People|AnnSmith')
    sharing.set_photo_scope(conn, pid, person, {'mode': 'fronts'})
    overrides = {primary: 'separate-example'}
    group(conn, overrides=overrides)
    assert conn.execute('SELECT COUNT(*) FROM photos').fetchone()[0] == 2
    assert conn.execute('SELECT image_id FROM faces WHERE id=?', (fid,)).fetchone()[0] == primary
    split = conn.execute('SELECT photo_id FROM images WHERE id=?', (primary,)).fetchone()[0]
    assert sharing.resolve_scope(conn, split, person)[0]['mode'] == 'fronts'
    group(conn, overrides={})
    assert conn.execute('SELECT COUNT(*) FROM photos').fetchone()[0] == 1


def test_stale_group_preview_is_rejected(lib):
    conn, root = lib
    trio(conn, root)
    p = variations.preview(conn, config())
    conn.execute("UPDATE photos SET notes='New note'")
    conn.commit()
    with pytest.raises(ValueError, match='changed'):
        variations.apply(conn, config(), p['token'])


def test_different_extensions_and_identical_files_remain_versions(lib):
    conn, root = lib
    cfg = config()
    db.set_setting(conn, variations.SETTING, json.dumps(cfg)); conn.commit()
    p = photo(root, 'Scan_0001.jpg')
    (root / 'Scan_0001_a.jpg').write_bytes(p.read_bytes())
    register(conn, root)
    group(conn)
    assert conn.execute('SELECT COUNT(*) FROM images').fetchone()[0] == 2
    assert conn.execute('SELECT COUNT(*) FROM photos').fetchone()[0] == 1


def test_bad_rules_are_rejected_without_overwriting_saved_preferences(lib):
    conn, _ = lib
    with pytest.raises(ValueError):
        sharing.save(conn, {'rules': [{'target': 'hierarchy', 'path': 'People', 'scope': {'mode': 'selected', 'suffixes': []}}]})
    assert sharing.load(conn) == sharing.DEFAULT
    cfg = config(); cfg['types'][1]['suffix'] = '_b'
    with pytest.raises(ValueError):
        variations.validate(cfg)


def test_nested_hierarchy_rule_beats_parent_and_keyword_beats_both(lib):
    conn, root = lib
    photo(root, 'Item_0001.jpg', ['People|Friends|AnnSmith'])
    photo(root, 'Item_0001_a.jpg')
    register(conn, root); pid = group(conn)
    k = kid(conn, 'People|Friends|AnnSmith')
    sharing.save(conn, {'rules': [
        {'target': 'hierarchy', 'path': 'People', 'scope': {'mode': 'all'}},
        {'target': 'hierarchy', 'path': 'People|Friends', 'scope': {'mode': 'current'}},
    ]})
    assert sharing.resolve_scope(conn, pid, k)[0]['mode'] == 'current'
    assert not sharing.review(conn)['differences']
    current = sharing.load(conn)
    current['rules'].append({'target': 'keyword', 'path': 'People|Friends|AnnSmith', 'scope': {'mode': 'fronts'}})
    sharing.save(conn, current)
    assert sharing.resolve_scope(conn, pid, k)[0]['mode'] == 'fronts'
    assert len(sharing.review(conn)['differences']) == 1


def test_external_keyword_edits_are_seen_and_unreadable_files_reported(lib):
    conn, root = lib
    paths = trio(conn, root); group(conn)
    with pyexiv2.Image(str(paths[1])) as im:
        im.modify_xmp({xmp.HS: ['People|AnnSmith']})
    differences = sharing.review(conn)['differences']
    assert len([d for d in differences if d['keyword'] == 'People|AnnSmith']) == 1
    assert any(d['reason'] == 'Missing hierarchy' and d['keyword'] == 'Attributes|portrait' for d in differences)
    paths[2].unlink()
    audit = sharing.review(conn)
    assert len(audit['errors']) == 1
    assert audit['errors'][0]['path'] == paths[2].name
    assert not [d for d in audit['differences'] if d['path'] == paths[2].name]


def test_review_keep_current_exception_survives_preference_changes(lib):
    conn, root = lib
    paths = trio(conn, root); group(conn)
    missing = next(d for d in sharing.review(conn)['differences'] if d['path'] == paths[2].name)
    sharing.exception(conn, missing['image_id'], missing['keyword_id'], missing['present'])
    sharing.save(conn, {'rules': [{'target': 'hierarchy', 'path': 'People', 'scope': {'mode': 'all'}}]})
    r = sharing.review(conn)
    assert not [d for d in r['differences'] if d['path'] == paths[2].name and d['keyword_id'] == missing['keyword_id']]
    assert r['exceptions'][0]['expected'] is False


def test_partial_write_failure_is_reported_and_successes_remain_consistent(lib, monkeypatch):
    conn, root = lib
    trio(conn, root); group(conn)
    changes = [d for d in sharing.review(conn)['differences'] if d['keyword'] == 'People|AnnSmith']
    blocked = changes[0]['image_id']
    real = sharing.write_one
    def fake(conn, image_id, *args, **kwargs):
        if image_id == blocked:
            raise OSError('File is locked')
        return real(conn, image_id, *args, **kwargs)
    monkeypatch.setattr(sharing, 'write_one', fake)
    result = sharing.apply_review(conn, [{'id': d['id']} for d in changes])
    assert len(result['completed']) == 1 and len(result['errors']) == 1
    remaining = [d for d in result['review']['differences'] if d['keyword'] == 'People|AnnSmith']
    assert len(remaining) == 1 and remaining[0]['image_id'] == blocked


def test_current_scope_adds_attribute_only_to_active_version(lib):
    conn, root = lib
    paths = trio(conn, root); pid = group(conn)
    k = kid(conn, 'Attributes|reviewed')
    back = conn.execute("SELECT id FROM images WHERE role='back'").fetchone()[0]
    sharing.set_photo_scope(conn, pid, k, {'mode': 'current'})
    sharing.add(conn, pid, k, active_image=back)
    assert 'Attributes|reviewed' in xmp.read(paths[2]).keywords
    assert all('Attributes|reviewed' not in xmp.read(p).keywords for p in paths[:2])


def test_ask_records_pending_choice_without_arbitrary_file_writes(lib):
    conn, root = lib
    paths = trio(conn, root); pid = group(conn)
    k = kid(conn, 'Attributes|reviewed')
    sharing.save(conn, {'rules': [{'target': 'hierarchy', 'path': 'Attributes', 'scope': {'mode': 'ask'}}]})
    before = [p.read_bytes() for p in paths]
    sharing.add(conn, pid, k)
    assert [p.read_bytes() for p in paths] == before
    assert any(c['keyword_id'] == k for c in sharing.review(conn)['choices'])


def test_existing_faces_on_non_recognition_versions_are_kept_but_not_training(lib):
    from backend import match, cluster
    conn, root = lib
    trio(conn, root); group(conn)
    person = conn.execute("SELECT id FROM people WHERE name='Ann Smith'").fetchone()[0]
    original = conn.execute("SELECT id FROM images WHERE variation=''").fetchone()[0]
    primary = conn.execute('SELECT id FROM images WHERE recognition_enabled=1').fetchone()[0]
    old = make_face(conn, original, person)
    assert match.Gallery.load(conn) is None
    new = make_face(conn, primary, person)
    assert list(match.Gallery.load(conn).face_ids) == [new]
    assert conn.execute('SELECT status FROM faces WHERE id=?', (old,)).fetchone()[0] == 'confirmed'
    assert cluster.cluster(conn) == 0


def test_flat_original_removal_saves_prior_values_for_strip(lib):
    conn, root = lib
    p = photo(root, 'Scan_0001.jpg')
    k = kid(conn, 'People|AnnSmith')
    with pyexiv2.Image(str(p)) as im:
        im.modify_xmp({xmp.SUBJ: ['AnnSmith']})
        im.modify_iptc({xmp.IPTC_KW: ['AnnSmith']})
    register(conn, root); group(conn)
    image = conn.execute('SELECT id FROM images').fetchone()[0]
    sharing.write_one(conn, image, k, False, only_app=False)
    assert not xmp.read(p).flat and not xmp.read(p).other
    xmp.strip_app_keywords(p); xmp.restore_fields(p)
    assert xmp.read(p).flat == ['AnnSmith'] and xmp.read(p).other == ['AnnSmith']


def test_serial_variations_can_contain_digits_if_mapped():
    cfg = config(pattern='serial')
    cfg['types'].append({'suffix': '_edit2', 'label': 'Second edit', 'role': 'front'})
    assert variations.classify('album/36_Topic_0005_edit2.jpg', cfg)['key'] == 'album/36_topic_0005'


def test_api_group_apply_backs_up_db_and_scope_save_does_not_write_photos(lib):
    conn, root = lib
    paths = trio(conn, root)
    before = [p.read_bytes() for p in paths]
    body = api.VariationPlanIn(config=config(), overrides={})
    plan = api.variation_preview(body, conn)
    body.token = plan['token']
    result = api.variation_apply(body, conn)
    assert __import__('pathlib').Path(result['backup']).exists()
    assert [p.read_bytes() for p in paths] == before
    # Libraries and older clients may still carry the old auto-check preference.
    db.set_setting(conn, sharing.SETTING, json.dumps({'rules': [], 'check_on_save': True}))
    db.set_setting(conn, 'sharing.pending', '42')
    assert api.sharing_get(conn) == {'rules': []}
    saved = api.sharing_save({'rules': [], 'check_on_save': True}, conn)
    assert saved == {'rules': []}
    assert db.get_setting(conn, 'sharing.pending') == '42'
    review = api.sharing_review(conn=conn)
    assert review['photos_checked'] == 1
    assert review['differences']
    assert [p.read_bytes() for p in paths] == before


def test_saving_sharing_preferences_during_scan_does_not_wait_for_scan_lock(lib, monkeypatch):
    conn, _ = lib
    monkeypatch.setattr(api.JOB, 'state', {'running': True})
    monkeypatch.setattr(variations, 'LOCK', None)
    with pytest.raises(api.HTTPException, match='Wait for the photo scan') as exc:
        api.sharing_save({'rules': [], 'check_on_save': True}, conn)
    assert exc.value.status_code == 409


def test_explicit_owner_removal_after_app_additions_restores_pre_app_baseline(lib):
    conn, root = lib
    p = photo(root, 'Scan_0001.jpg', ['Attributes|portrait'])
    xmp.add_keywords(p, ['People|AnnSmith'])
    xmp.remove_keywords(p, ['Attributes|portrait'], only_app_added=False)
    xmp.strip_app_keywords(p); xmp.restore_fields(p)
    assert xmp.read(p).keywords == ['Attributes|portrait']
    assert xmp.read(p).flat == ['portrait']
    assert xmp.read(p).other == ['portrait']


def test_group_preview_leaves_keyword_review_to_saved_scan_families(lib):
    conn, root = lib
    paths = trio(conn, root)
    before = [p.read_bytes() for p in paths]
    p = api.variation_preview(api.VariationPlanIn(config=config()), conn)
    assert len(p['groups']) == 1 and 'review' not in p
    assert conn.execute('SELECT COUNT(*) FROM photos').fetchone()[0] == 2
    api.variation_apply(api.VariationPlanIn(config=config(), token=p['token']), conn)
    assert len(sharing.review(conn)['differences']) == 6
    assert [p.read_bytes() for p in paths] == before


def test_unmapped_suffix_is_reported_after_import(lib, monkeypatch):
    conn, root = lib
    trio(conn, root); group(conn)
    photo(root, 'Series_0005_z.jpg')
    monkeypatch.setattr(ingest, 'scan_faces', lambda *a, **kw: (0, 0))
    result = ingest.ingest(conn, root, root / 'thumbs')
    assert result['variation_issues'] == 1
    audit = sharing.review(conn)
    assert audit['grouping_issues'][0]['suffix'] == '_z'
    assert conn.execute('SELECT COUNT(*) FROM photos').fetchone()[0] == 2


def test_keep_present_exception_survives_face_rejection(lib):
    conn, root = lib
    paths = trio(conn, root); group(conn)
    k = kid(conn, 'People|AnnSmith')
    person = conn.execute('SELECT person_id FROM keywords WHERE id=?', (k,)).fetchone()[0]
    primary = conn.execute('SELECT id FROM images WHERE is_primary=1').fetchone()[0]
    fid = make_face(conn, primary)
    actions.assign(conn, [fid], person)
    sharing.exception(conn, primary, k, True)
    actions.reject(conn, [fid])
    assert 'People|AnnSmith' in xmp.read(paths[1]).keywords


def test_ask_preserves_and_reports_deliberate_exceptions(lib):
    conn, root = lib
    paths = trio(conn, root); group(conn)
    k = kid(conn, 'Attributes|portrait')
    back = conn.execute("SELECT id FROM images WHERE role='back'").fetchone()[0]
    sharing.exception(conn, back, k, False)
    sharing.save(conn, {'rules': [{'target': 'hierarchy', 'path': 'Attributes', 'scope': {'mode': 'ask'}}]})
    audit = sharing.review(conn)
    assert any(e['image_id'] == back and e['keyword_id'] == k for e in audit['exceptions'])
    assert any(c['keyword_id'] == k for c in audit['choices'])


def test_pause_keeps_existing_groups_and_files(lib):
    conn, root = lib
    paths = trio(conn, root); group(conn)
    before = [p.read_bytes() for p in paths]
    api.variation_pause(conn)
    assert not variations.load(conn)['enabled']
    assert conn.execute('SELECT COUNT(*) FROM photos').fetchone()[0] == 1
    assert [p.read_bytes() for p in paths] == before


def test_flat_keyword_is_reviewed_for_missing_hierarchy_and_can_be_preserved(lib):
    conn, root = lib
    k = kid(conn, 'People|AnnSmith')
    p = photo(root, 'Flat_0001.jpg')
    with pyexiv2.Image(str(p)) as im:
        im.modify_xmp({xmp.SUBJ: ['AnnSmith']})
        im.modify_iptc({xmp.IPTC_KW: ['AnnSmith']})
    register(conn, root); group(conn)
    change = sharing.review(conn)['differences'][0]
    assert change['reason'] == 'Missing hierarchy'
    assert change['present'] and change['expected']
    sharing.exception(conn, change['image_id'], k, True)
    assert not sharing.review(conn)['differences']
    sharing.exception(conn, change['image_id'], k, None)
    sharing.apply_review(conn, [{'id': change['id']}])
    assert xmp.read(p).keywords == ['People|AnnSmith']
    xmp.strip_app_keywords(p)
    assert xmp.read(p).flat == ['AnnSmith']


def test_exclusive_rule_flags_duplicates_and_requires_a_keeper(lib):
    from fastapi import HTTPException

    conn, root = lib
    paths = trio(conn, root)
    pid = group(conn)
    name = 'Attributes|preferred'
    k = kid(conn, name)
    ids = {r['path']: r['id'] for r in conn.execute('SELECT id,path FROM images')}
    for path in paths[:2]:
        xmp.add_keywords(path, [name])
    originals = [p.read_bytes() for p in paths]
    sharing.save(conn, {'rules': [{'target': 'keyword', 'path': name, 'scope': {'mode': 'one'}}]})
    report = sharing.review(conn)
    assert len(report['conflicts']) == 1
    conflict = report['conflicts'][0]
    assert {v['path'] for v in conflict['variants']} == {p.name for p in paths[:2]}
    assert not [d for d in report['differences'] if d['keyword_id'] == k]
    assert [p.read_bytes() for p in paths] == originals
    with pytest.raises(HTTPException):
        api.sharing_keep_one(api.ExclusiveIn(conflict_id=conflict['id'], keep_image_id=ids[paths[1].name]), conn)
    assert [p.read_bytes() for p in paths] == originals
    api.sharing_keep_one(api.ExclusiveIn(conflict_id=conflict['id'], keep_image_id=ids[paths[1].name],
                                        confirm_removals=True), conn)
    assert [name in xmp.read(p).keywords for p in paths] == [False, True, False]
    assert not sharing.review(conn)['conflicts']
    with pytest.raises(ValueError, match='limited to one'):
        sharing.add(conn, pid, k, active_image=ids[paths[2].name])
    assert name not in xmp.read(paths[2]).keywords


def test_keep_separate_overrides_all_variants_default(lib):
    conn, root = lib
    trio(conn, root)
    pid = group(conn)
    hide = kid(conn, 'Attributes|hide')
    portrait = kid(conn, 'Attributes|portrait')
    sharing.save(conn, {'rules': [{'target': 'keyword', 'path': 'Attributes|hide', 'scope': {'mode': 'current'}}]})
    report = sharing.review(conn)
    assert sharing.resolve_scope(conn, pid, portrait)[0]['mode'] == 'all'
    assert not any(row['keyword_id'] == hide for row in report['differences'])
    assert len([row for row in report['differences'] if row['keyword_id'] == portrait]) == 2

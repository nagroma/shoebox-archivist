"""The Faces view can select files independently of the recognition scan."""
from backend import api, db, face_review, keywords, variations


def image(conn, path, *, photo=None, suffix='', label='', role='front', recognize=1, scanned=1):
    photo = photo or conn.execute('INSERT INTO photos DEFAULT VALUES').lastrowid
    return conn.execute('INSERT INTO images(photo_id,path,sha1,role,variation,variation_label,'
                        'recognition_enabled,faces_scanned) VALUES(?,?,?,?,?,?,?,?)',
                        (photo, path, path, role, suffix, label, recognize, scanned)).lastrowid


def face(conn, img, *, status='unknown', candidate=0):
    return conn.execute('INSERT INTO faces(image_id,x1,y1,x2,y2,status,candidate) VALUES(?,0,0,1,1,?,?)',
                        (img, status, candidate)).lastrowid


def review_ids(result):
    return {f['id'] for c in result['clusters'] for f in c['faces']}


def test_suggested_faces_show_only_people_keywords_already_on_the_photo(tmp_path):
    with db.connect(tmp_path / 'library.db') as c:
        photo = c.execute('INSERT INTO photos DEFAULT VALUES').lastrowid
        original = image(c, 'Photo.jpg', photo=photo)
        corrected = image(c, 'Photo_a.jpg', photo=photo)
        suggested = face(c, corrected, status='suggested')
        unknown = face(c, corrected)
        person = db.get_or_create_person(c, 'Suggested Person')
        c.execute('UPDATE faces SET person_id=? WHERE id=?', (person, suggested))
        for category, name, kind in [('People|Friends', 'AlreadyTagged', 'person'),
                                     ('Subjects', 'Portrait', 'subject')]:
            kid = keywords.ensure(c, category, name, kind=kind)
            c.execute("INSERT INTO image_keywords(image_id,keyword_id,source) VALUES(?,?,'file')",
                      (original, kid))
            c.execute("INSERT INTO photo_keywords(photo_id,keyword_id,source) VALUES(?,?,'file')",
                      (photo, kid))
        c.commit()

        expected = ['People|Friends|AlreadyTagged']
        assert api.person(person, c)['suggested'][0]['people_keywords'] == expected
        visible = {f['id']: f for cluster in api.faces_review(c)['clusters'] for f in cluster['faces']}
        assert visible[suggested]['people_keywords'] == expected
        assert visible[unknown]['people_keywords'] == []


def test_corrected_when_present_original_when_missing_across_folders(tmp_path):
    with db.connect(tmp_path / 'library.db') as c:
        original = image(c, 'Scans/Photo.jpg')
        corrected = image(c, 'Scans/Photo_a.jpg')
        lone = image(c, 'Originals/Photo.jpg')
        # The corrected file exists but has no detections: its original stays hidden.
        hidden = face(c, original)
        shown = face(c, lone)
        selected, view = face_review.plan(c)
        assert selected == {corrected, lone}
        assert view['fallback'] == 1
        assert review_ids(api.faces_review(c)) == {shown}
        updated = api.faces_review_save(api.FaceViewIn(also_show=['']), c)
        assert review_ids(updated) == {shown, hidden}
        assert review_ids(api.faces_review(c)) == {shown, hidden}
        assert c.execute('SELECT COUNT(*) FROM photos').fetchone()[0] == 3


def test_filter_changes_all_face_sections_without_changing_recognition(tmp_path):
    with db.connect(tmp_path / 'library.db') as c:
        pid = c.execute('INSERT INTO photos DEFAULT VALUES').lastrowid
        original = image(c, 'Photo.jpg', photo=pid, label='Original', recognize=0)
        corrected = image(c, 'Photo_a.jpg', photo=pid, suffix='_a', label='Corrected')
        back = image(c, 'Photo_b.jpg', photo=pid, suffix='_b', label='Back', role='back', recognize=0)
        orig_face, corr_face = face(c, original), face(c, corrected)
        orig_candidate, corr_candidate = face(c, original, candidate=1), face(c, corrected, candidate=1)
        orig_ignored, back_ignored = face(c, original, status='ignored'), face(c, back, status='ignored')
        initial = api.faces_review(c)
        assert review_ids(initial) == {corr_face}
        assert [f['id'] for f in initial['candidates']['faces']] == [corr_candidate]
        assert not initial['ignored']
        combined = api.faces_review_save(api.FaceViewIn(also_show=['', '_b']), c)
        assert review_ids(combined) == {orig_face, corr_face}
        assert {f['id'] for f in combined['candidates']['faces']} == {orig_candidate, corr_candidate}
        assert {f['id'] for f in combined['ignored']} == {orig_ignored, back_ignored}
        assert [r[0] for r in c.execute('SELECT recognition_enabled FROM images ORDER BY id')] == [0, 1, 0]
        assert db.get_setting(c, variations.SETTING) is None


def test_custom_mapping_and_per_library_preferences(tmp_path):
    import json
    with db.connect(tmp_path / 'first.db') as c, db.connect(tmp_path / 'second.db') as other:
        cfg = {**variations.DEFAULT, 'recognition': '_b', 'preferred': '_b', 'types': [
            {'suffix': '', 'label': 'Original', 'role': 'front'},
            {'suffix': '_a', 'label': 'Reverse', 'role': 'back'},
            {'suffix': '_b', 'label': 'Enhanced', 'role': 'front'},
        ]}
        db.set_setting(c, variations.SETTING, json.dumps(cfg))
        original = image(c, 'Photo.jpg')
        image(c, 'Photo_a.jpg')
        corrected = image(c, 'Photo_b.jpg', scanned=0)
        assert face_review.plan(c)[0] == {corrected}
        assert face_review.plan(c)[1]['unscanned'] == 1
        api.faces_review_save(api.FaceViewIn(preferred=''), c)
        assert face_review.plan(c)[0] == {original}
        assert face_review.plan(other)[1]['preferred'] is None


def test_applied_keep_separate_groups_stay_separate(tmp_path):
    with db.connect(tmp_path / 'library.db') as c:
        original = image(c, 'Photo.jpg', label='Original')
        corrected = image(c, 'Photo_a.jpg', suffix='_a', label='Corrected')
        assert face_review.plan(c)[0] == {original, corrected}


def test_clustering_uses_displayed_variants_not_recognition_flags(tmp_path, monkeypatch):
    import numpy as np
    from backend import cluster

    with db.connect(tmp_path / 'library.db') as c:
        pid = c.execute('INSERT INTO photos DEFAULT VALUES').lastrowid
        original = image(c, 'Photo.jpg', photo=pid, label='Original', recognize=0)
        corrected = image(c, 'Photo_a.jpg', photo=pid, suffix='_a', label='Corrected')
        fallback = image(c, 'Other.jpg', label='Original')
        hidden = face(c, original)
        preferred = face(c, corrected)
        original_only = face(c, fallback)
        candidate = face(c, corrected, candidate=1)
        c.execute('UPDATE faces SET embedding=?, cluster_id=5', (np.ones(512, dtype=np.float32).tobytes(),))

        # Without the hidden original, there are too few eligible faces for a cluster.
        assert cluster.cluster(c, min_cluster_size=3) == 0
        assert not c.execute('SELECT 1 FROM faces WHERE cluster_id IS NOT NULL').fetchone()

        class OneCluster:
            def __init__(self, *, min_cluster_size, **kwargs):
                assert min_cluster_size == 3

            def fit_predict(self, embeddings):
                assert len(embeddings) == 3
                return np.zeros(len(embeddings), dtype=int)

        monkeypatch.setattr(cluster, 'HDBSCAN', OneCluster)
        api.faces_review_save(api.FaceViewIn(also_show=['']), c)
        assert cluster.cluster(c, min_cluster_size=3) == 1
        assignments = dict(c.execute('SELECT id,cluster_id FROM faces'))
        assert assignments == {hidden: 0, preferred: 0, original_only: 0, candidate: None}
        assert [r[0] for r in c.execute('SELECT recognition_enabled FROM images ORDER BY id')] == [0, 1, 1]
